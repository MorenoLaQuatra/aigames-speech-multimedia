"""Image generation worker for the "drawing" game (Visual Taboo AI).

Models, all loaded at start-up on models.workers.image_gen.device:
  1. text-to-image: games.drawing.image_model selects one entry of
     games.drawing.image_models (sd-turbo: small, works on CPU; FLUX.2 klein
     4B and Z-Image-Turbo: much more accurate, need the GPU and read Italian
     directly);
  2. translation it->en (Marian, games.drawing.translation_model_id), only
     loaded when the selected image model has translate_prompt: true -
     sd-turbo only understands English well;
  3. open-vocabulary detector (games.drawing.detector_model_id, OWLv2) that
     checks which of the challenge's elements really appear in the image.

GPU memory (image_models.<name>.cuda_memory):
  full           - whole pipeline on the GPU (small models);
  model_offload  - each component moves to the GPU only while it runs;
  group_offload  - weights stay in system RAM and stream to the GPU block by
                   block: lowest VRAM (a 6B model fits in a few GB), slower.
  stream_text_encoder - everything resident on the GPU except the text
                   encoder, whose weights stream layer by layer from pinned
                   system RAM. For models whose denoiser fits but not together
                   with the text encoder: model_offload would copy whole
                   models across PCIe on every image (FLUX.2 klein 4B on the
                   RTX 5000: ~20 s with model_offload, ~4 s with this).

float16 on Turing GPUs (image_models.<name>.cuda_fp16_guard): Turing has no
fast bfloat16, but Z-Image in plain float16 overflows (65504) in a few ops and
draws black images. With the guard those ops run in float32 - see
guard_fp16_overflow(). On the Quadro RTX 5000: ~36 s per 768px image, 11.9 GiB
peak, same images as bfloat16 (which takes ~75 s and 13.1 GiB).

POST /generate  JSON {"prompt", "language": "it"|"en", "queries": [str], "threshold": float}
  -> {"translated": English text, or "" when the prompt went in untranslated,
      "seed", "image_png_base64",
      "detections": [{"score": float, "box": [x0, y0, x1, y1] | null, "found": bool}],
      "timings": {"translate", "generate", "detect"}}   (seconds)
"""

import base64
import functools
import io
import logging
import random
import time

from common import create_worker_app, json_error, load_worker_config, resolve_device, serve

import torch  # noqa: E402
from diffusers import DiffusionPipeline  # noqa: E402
from diffusers.hooks import apply_group_offloading  # noqa: E402
from flask import jsonify, request  # noqa: E402
from torch.nn import functional as F  # noqa: E402
from transformers import MarianMTModel, MarianTokenizer, Owlv2ForObjectDetection, Owlv2Processor  # noqa: E402

DTYPES = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
MEMORY_MODES = ("full", "model_offload", "group_offload", "stream_text_encoder")

config, worker_cfg, worker_name = load_worker_config()
log = logging.getLogger(worker_name)
game_cfg = config.games.drawing
model_cfg = game_cfg.image_models[game_cfg.image_model]
device = resolve_device(worker_cfg.device)
torch.set_num_threads(max(1, torch.get_num_threads()))

if device.type == "cuda":
    dtype = DTYPES[model_cfg.cuda_dtype]
    memory_mode = model_cfg.cuda_memory
    if memory_mode not in MEMORY_MODES:
        raise ValueError(f"cuda_memory must be one of {MEMORY_MODES}, got {memory_mode!r}")
else:
    dtype = DTYPES[model_cfg.cpu_dtype]
    memory_mode = "full"



def _linear_float32(linear, x):
    bias = None if linear.bias is None else linear.bias.float()
    return F.linear(x.float(), linear.weight.float(), bias)


def _silu_gating_float32(x1, x3):
    return F.silu(x1.float()) * x3.float()


def guard_fp16_overflow(transformer):
    """Z-Image transformer in float16: the attention and feed-forward output
    projections and the SwiGLU product exceed float16's range in some layers.
    Each of them feeds an RMSNorm, so computing just these in float32 (weights
    stay float16) removes the overflow while the rest keeps float16 speed."""
    projections = gates = 0
    for name, module in transformer.named_modules():
        if name.endswith(("attention.to_out.0", "feed_forward.w2")):
            module.forward = functools.partial(_linear_float32, module)
            projections += 1
        elif name.endswith("feed_forward"):
            module._forward_silu_gating = _silu_gating_float32
            gates += 1
    if projections == 0 or gates == 0:
        raise RuntimeError(f"cuda_fp16_guard: expected Z-Image blocks, found {projections} projections, {gates} gates")
    log.info("fp16 guard: %d projections and %d gates in float32", projections, gates)


def stream_text_encoder(pipeline, gpu):
    """Every model of the pipeline on the GPU, except the text encoder, which
    streams its weights per layer from pinned system RAM (one prompt per
    image, so its compute is tiny and the transfer is what counts)."""
    text_encoder = pipeline.text_encoder
    if hasattr(text_encoder, "lm_head"):
        # Causal-LM text encoders (FLUX.2 klein: Qwen3ForCausalLM): the
        # pipeline reads hidden states only, the vocabulary head (~0.8 GB) is
        # never used.
        text_encoder.lm_head = torch.nn.Identity()
    for name, component in pipeline.components.items():
        if isinstance(component, torch.nn.Module) and component is not text_encoder:
            component.to(gpu)
    apply_group_offloading(text_encoder, onload_device=gpu, offload_device=torch.device("cpu"),
                           offload_type="leaf_level", use_stream=True)


translator = None
if model_cfg.translate_prompt:
    translator_tokenizer = MarianTokenizer.from_pretrained(game_cfg.translation_model_id)
    translator = MarianMTModel.from_pretrained(game_cfg.translation_model_id).to(device).eval()

log.info("Loading %s (%s) on %s, %s, memory=%s", game_cfg.image_model, model_cfg.model_id, device, dtype, memory_mode)
pipe = DiffusionPipeline.from_pretrained(model_cfg.model_id, torch_dtype=dtype)
if device.type == "cuda" and dtype == torch.float16 and model_cfg.cuda_fp16_guard:
    guard_fp16_overflow(pipe.transformer)
if memory_mode == "full":
    pipe = pipe.to(device)
elif memory_mode == "model_offload":
    pipe.enable_model_cpu_offload(device=device)
elif memory_mode == "stream_text_encoder":
    stream_text_encoder(pipe, device)
else:
    pipe.enable_group_offload(onload_device=device, offload_device=torch.device("cpu"),
                              offload_type="leaf_level", use_stream=True)
pipe.set_progress_bar_config(disable=True)

detector_processor = Owlv2Processor.from_pretrained(game_cfg.detector_model_id)
detector = Owlv2ForObjectDetection.from_pretrained(game_cfg.detector_model_id).to(device).eval()
log.info("Ready")

app = create_worker_app(worker_name)


@torch.inference_mode()
def translate(text):
    """Italian -> English, for image models that only understand English well."""
    batch = translator_tokenizer([text], return_tensors="pt", truncation=True, max_length=256).to(device)
    output = translator.generate(**batch, max_new_tokens=256, num_beams=4)
    return translator_tokenizer.decode(output[0], skip_special_tokens=True)


@torch.inference_mode()
def generate(prompt, seed):
    generator = torch.Generator(device="cpu").manual_seed(seed)
    result = pipe(
        prompt=prompt,
        num_inference_steps=model_cfg.inference_steps,
        guidance_scale=model_cfg.guidance_scale,
        height=model_cfg.image_size,
        width=model_cfg.image_size,
        generator=generator,
    )
    return result.images[0]


@torch.inference_mode()
def detect(image, queries, threshold):
    """Best box per query. OWLv2 pads the image to a square, so boxes come
    back in the padded frame - here the image is already square."""
    inputs = detector_processor(text=[queries], images=image, return_tensors="pt").to(device)
    outputs = detector(**inputs)
    size = max(image.size)
    logits = outputs.logits[0].sigmoid()            # [num_boxes, num_queries]
    boxes = outputs.pred_boxes[0]                   # [num_boxes, 4] cx, cy, w, h (0-1)
    detections = []
    for qi in range(len(queries)):
        best = int(torch.argmax(logits[:, qi]))
        score = float(logits[best, qi])
        cx, cy, w, h = boxes[best].tolist()
        box = [
            max(0.0, (cx - w / 2) * size), max(0.0, (cy - h / 2) * size),
            min(image.size[0], (cx + w / 2) * size), min(image.size[1], (cy + h / 2) * size),
        ]
        detections.append({"score": round(score, 4), "box": [round(v, 1) for v in box], "found": score >= threshold})
    return detections


@app.route("/generate", methods=["POST"])
def generate_route():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return json_error("JSON body required", 400)
    prompt = str(body.get("prompt", "")).strip()
    language = body.get("language")
    queries = body.get("queries")
    threshold = body.get("threshold")
    if not prompt:
        return json_error("Empty prompt", 400)
    if language not in ("it", "en"):
        return json_error("language must be 'it' or 'en'", 400)
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q for q in queries):
        return json_error("queries must be a non-empty list of strings", 400)
    if not isinstance(threshold, (int, float)):
        return json_error("threshold must be a number", 400)

    timings = {}
    start = time.perf_counter()
    translated = translate(prompt) if translator is not None and language == "it" else ""
    timings["translate"] = round(time.perf_counter() - start, 2)

    seed = random.randint(0, 2**31 - 1)
    start = time.perf_counter()
    image = generate(translated or prompt, seed)
    timings["generate"] = round(time.perf_counter() - start, 2)

    start = time.perf_counter()
    detections = detect(image, queries, float(threshold))
    timings["detect"] = round(time.perf_counter() - start, 2)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return jsonify({
        "translated": translated,
        "seed": seed,
        "image_png_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "detections": detections,
        "timings": timings,
    })


if __name__ == "__main__":
    serve(app, worker_cfg)
