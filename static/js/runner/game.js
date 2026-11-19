/* RunnerGame: a slow, forgiving 3-lane runner on a <canvas>, drawn in
 * perspective (Temple Run style; the game logic itself is flat, see draw()).
 *
 * Deliberately slow: sound recognition takes ~0.3-0.8 s, so every obstacle
 * is on screen for settings.fallSeconds before it reaches the runner, and
 * rows are settings.spawnIntervalSeconds apart. Commands: "left", "right",
 * "jump" (jumping clears obstacles for settings.jumpSeconds).
 *
 *   const game = new RunnerGame(canvas, settings, { onHud, onEnd });
 *   game.start();               // onEnd({coins, seconds, hits, reason}) when over
 *   game.command("left");
 *   game.stop();                // abort without onEnd
 *
 * Colours come from the page's CSS tokens, so the canvas follows the theme.
 */

(function () {
  "use strict";

  const WIDTH = 600;
  const HEIGHT = 760;
  const LANES = [100, 300, 500];
  const PLAYER_Y = 650;
  const PLAYER_SIZE = 76;
  const ITEM_SIZE = 70;
  const SPAWN_Y = -ITEM_SIZE;
  const INVULNERABLE_SECONDS = 1.2;
  const LANE_MOVE_SECONDS = 0.15;
  const DOUBLE_OBSTACLE_CHANCE = 0.25;
  const COIN_CHANCE = 0.85;
  const COMMAND_FLASH_SECONDS = 0.5;
  const ARROWS = { left: "←", right: "→", jump: "↑" };
  // Perspective drawing (see draw()).
  const CENTER_X = WIDTH / 2;
  const HORIZON_Y = 120;
  const RUNNER_SCREEN_Y = 690;
  const CAMERA_DISTANCE = 300;
  const FAR_DISTANCE = PLAYER_Y - SPAWN_Y;   // where items appear
  const NEAR_DISTANCE = 140;                 // drawn this far past the runner
  const PATH_LEFT = 0;
  const PATH_RIGHT = 600;
  const BAND = 40;
  const TREE_SPACING = 130;
  const JUMP_HEIGHT = 90;

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function randomInt(n) {
    return Math.floor(Math.random() * n);
  }

  class RunnerGame {
    constructor(canvas, settings, callbacks) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.settings = settings;
      this.onHud = callbacks.onHud;
      this.onEnd = callbacks.onEnd;
      this.running = false;
      this.speed = (PLAYER_Y - SPAWN_Y) / settings.fallSeconds;
      this.readColors();
      this.resetState();
      this.draw();
    }

    readColors() {
      this.colors = {
        bg: token("--surface"),
        lane: token("--border"),
        player: token("--accent"),
        playerText: token("--accent-text"),
        jump: token("--highlight"),
        obstacle: token("--danger"),
        obstacleText: token("--danger-text"),
        coin: token("--highlight"),
        coinEdge: token("--highlight-text"),
        text: token("--brand-dark"),
        skin: token("--runner-skin"),
        sky: token("--runner-sky"),
        hills: token("--runner-hills"),
        ground: token("--runner-ground"),
        groundAlt: token("--runner-ground-alt"),
        path: token("--runner-path"),
        pathAlt: token("--runner-path-alt"),
        pathEdge: token("--runner-path-edge"),
        trunk: token("--runner-trunk"),
        leaves: token("--runner-leaves"),
        shadow: token("--runner-shadow"),
      };
    }

    resetState() {
      this.items = [];
      this.lane = 1;
      this.playerX = LANES[1];
      this.elapsed = 0;
      this.nextSpawn = 0.5;
      this.coins = 0;
      this.hits = 0;
      this.lives = this.settings.lives;
      this.jumpUntil = -1;
      this.invulnerableUntil = -1;
      this.flash = null;
    }

    start() {
      this.readColors();
      this.resetState();
      this.running = true;
      this.lastFrame = performance.now();
      this.emitHud();
      this.frame = requestAnimationFrame((now) => this.loop(now));
    }

    stop() {
      this.running = false;
      cancelAnimationFrame(this.frame);
    }

    command(name) {
      if (!this.running) return;
      if (name === "left") this.lane = Math.max(0, this.lane - 1);
      else if (name === "right") this.lane = Math.min(2, this.lane + 1);
      else if (name === "jump" && this.elapsed >= this.jumpUntil) this.jumpUntil = this.elapsed + this.settings.jumpSeconds;
      this.flash = { name, until: this.elapsed + COMMAND_FLASH_SECONDS };
    }

    score() {
      return this.coins * this.settings.pointsPerCoin + Math.floor(this.elapsed) * this.settings.pointsPerSecond;
    }

    emitHud() {
      this.onHud({
        timeLeft: Math.max(0, Math.ceil(this.settings.runSeconds - this.elapsed)),
        lives: this.lives,
        coins: this.coins,
        score: this.score(),
      });
    }

    loop(now) {
      if (!this.running) return;
      const dt = Math.min(0.05, (now - this.lastFrame) / 1000);
      this.lastFrame = now;
      this.update(dt);
      this.draw();
      if (this.running) this.frame = requestAnimationFrame((t) => this.loop(t));
    }

    update(dt) {
      this.elapsed += dt;

      // Smooth lane change (visual only; collisions use the target lane).
      const targetX = LANES[this.lane];
      const step = (Math.abs(LANES[1] - LANES[0]) / LANE_MOVE_SECONDS) * dt;
      this.playerX += Math.max(-step, Math.min(step, targetX - this.playerX));

      if (this.elapsed >= this.nextSpawn) {
        this.spawnRow();
        this.nextSpawn += this.settings.spawnIntervalSeconds;
      }

      const jumping = this.elapsed < this.jumpUntil;
      const invulnerable = this.elapsed < this.invulnerableUntil;
      const reach = (PLAYER_SIZE + ITEM_SIZE) / 2;
      this.items.forEach((item) => {
        item.y += this.speed * dt;
        if (item.done || item.lane !== this.lane || Math.abs(item.y - PLAYER_Y) > reach * 0.7) return;
        if (item.type === "coin") {
          item.done = true;
          this.coins += 1;
        } else if (!jumping && !invulnerable) {
          item.done = true;
          this.hits += 1;
          this.lives -= 1;
          this.invulnerableUntil = this.elapsed + INVULNERABLE_SECONDS;
        }
      });
      this.items = this.items.filter((item) => !item.done && item.y < HEIGHT + ITEM_SIZE);

      this.emitHud();
      if (this.lives <= 0) this.finish("lives");
      else if (this.elapsed >= this.settings.runSeconds) this.finish("time");
    }

    spawnRow() {
      const lanes = [0, 1, 2].sort(() => Math.random() - 0.5);
      const obstacleCount = Math.random() < DOUBLE_OBSTACLE_CHANCE ? 2 : 1;
      for (let i = 0; i < obstacleCount; i++) this.items.push({ type: "obstacle", lane: lanes[i], y: SPAWN_Y });
      if (Math.random() < COIN_CHANCE) {
        // Coins sit in a free lane: going for them is the reward for moving.
        this.items.push({ type: "coin", lane: lanes[obstacleCount + randomInt(3 - obstacleCount)], y: SPAWN_Y });
      }
    }

    finish(reason) {
      this.running = false;
      this.onEnd({
        coins: this.coins,
        seconds: Math.min(this.settings.runSeconds, Math.floor(this.elapsed)),
        hits: this.hits,
        score: this.score(),
        reason,
      });
    }

    /* ----------------------------------------------------------- drawing
     *
     * The game runs in flat "world" coordinates (lanes at LANES, items moving
     * down towards PLAYER_Y); only the drawing is in perspective, Temple Run
     * style: the path runs away to the horizon, things grow as they approach.
     * Depth d = world distance ahead of the runner; scale(d) = CAM / (d + CAM). */

    scaleAt(d) {
      return CAMERA_DISTANCE / Math.max(d + CAMERA_DISTANCE, 1);
    }

    /* Screen point for world (x, distance ahead d). */
    project(x, d) {
      const scale = this.scaleAt(d);
      return {
        x: CENTER_X + (x - CENTER_X) * scale,
        y: HORIZON_Y + (RUNNER_SCREEN_Y - HORIZON_Y) * scale,
        scale,
      };
    }

    draw() {
      const ctx = this.ctx;
      const c = this.colors;
      const travelled = this.elapsed * this.speed;

      // Sky, distant hills, and the ground up to where the path begins.
      const groundY = this.project(0, FAR_DISTANCE).y;
      ctx.fillStyle = c.sky;
      ctx.fillRect(0, 0, WIDTH, HEIGHT);
      ctx.fillStyle = c.hills;
      ctx.beginPath();
      ctx.moveTo(0, groundY);
      for (let x = 0; x <= WIDTH; x += 20) {
        ctx.lineTo(x, groundY - 30 - 18 * Math.sin(x / 70) - 10 * Math.sin(x / 23 + 1));
      }
      ctx.lineTo(WIDTH, groundY);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = c.ground;
      ctx.fillRect(0, groundY, WIDTH, HEIGHT - groundY);

      // Ground and path in bands fixed to the world, so they slide towards
      // the runner as it moves; painted far to near.
      const firstBand = Math.floor((travelled - NEAR_DISTANCE - BAND) / BAND);
      const lastBand = Math.ceil((travelled + FAR_DISTANCE) / BAND);
      for (let k = lastBand; k >= firstBand; k--) {
        const far = Math.min((k + 1) * BAND - travelled, FAR_DISTANCE);
        const near = k * BAND - travelled;
        if (near >= FAR_DISTANCE) continue;
        const even = k % 2 === 0;
        const a = this.project(0, far);
        const b = this.project(0, near);
        ctx.fillStyle = even ? c.ground : c.groundAlt;
        ctx.fillRect(0, a.y, WIDTH, b.y - a.y + 1);
        this.quad(PATH_LEFT, PATH_RIGHT, far, near, even ? c.path : c.pathAlt);
      }
      // Path edges and lane dividers.
      [[PATH_LEFT, 6, c.pathEdge], [PATH_RIGHT, 6, c.pathEdge], [200, 2, c.pathEdge], [400, 2, c.pathEdge]]
        .forEach(([x, width, color]) => {
          const a = this.project(x, FAR_DISTANCE);
          const b = this.project(x, -NEAR_DISTANCE);
          ctx.strokeStyle = color;
          ctx.lineWidth = width;
          ctx.globalAlpha = width > 2 ? 1 : 0.45;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
          ctx.globalAlpha = 1;
        });

      // Trees on both sides and the items, painted far to near.
      const sprites = [];
      const treeOffset = travelled % TREE_SPACING;
      for (let d = FAR_DISTANCE + TREE_SPACING; d > -NEAR_DISTANCE; d -= TREE_SPACING) {
        const depth = d - treeOffset;
        if (depth > FAR_DISTANCE || depth < -NEAR_DISTANCE) continue;
        const index = Math.round((travelled + depth) / TREE_SPACING);
        sprites.push({ kind: "tree", x: PATH_LEFT - 90 - (index % 3) * 40, depth, size: 1 + (index % 2) * 0.25 });
        sprites.push({ kind: "tree", x: PATH_RIGHT + 90 + ((index + 1) % 3) * 40, depth, size: 1.25 - (index % 2) * 0.25 });
      }
      this.items.forEach((item) => {
        const depth = PLAYER_Y - item.y;
        if (depth < -NEAR_DISTANCE) return;
        sprites.push({ kind: item.type, x: LANES[item.lane], depth });
      });
      sprites.sort((p, q) => q.depth - p.depth);

      let runnerDrawn = false;
      sprites.forEach((sprite) => {
        if (!runnerDrawn && sprite.depth < 0) {
          this.drawPlayer();
          runnerDrawn = true;
        }
        const point = this.project(sprite.x, Math.min(sprite.depth, FAR_DISTANCE));
        // Fade in from the horizon so things don't pop up.
        ctx.globalAlpha = Math.max(0, Math.min(1, (FAR_DISTANCE - sprite.depth) / 120));
        if (sprite.kind === "tree") this.drawTree(point.x, point.y, point.scale * sprite.size);
        else if (sprite.kind === "obstacle") this.drawStopSign(point.x, point.y, point.scale);
        else this.drawCoin(point.x, point.y, point.scale);
        ctx.globalAlpha = 1;
      });
      if (!runnerDrawn) this.drawPlayer();

      if (this.flash && this.elapsed < this.flash.until) {
        ctx.fillStyle = c.text;
        ctx.font = "800 64px 'Rethink Sans', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "alphabetic";
        ctx.fillText(ARROWS[this.flash.name], this.project(this.playerX, 0).x, RUNNER_SCREEN_Y - PLAYER_SIZE * 1.9);
      }
    }

    /* Filled stretch of ground between world x0..x1, from distance far to near. */
    quad(x0, x1, far, near, color) {
      const ctx = this.ctx;
      const a = this.project(x0, far);
      const b = this.project(x1, far);
      const p = this.project(x1, near);
      const q = this.project(x0, near);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.lineTo(p.x, p.y);
      ctx.lineTo(q.x, q.y);
      ctx.closePath();
      ctx.fill();
    }

    shadow(x, y, width) {
      const ctx = this.ctx;
      ctx.fillStyle = this.colors.shadow;
      ctx.beginPath();
      ctx.ellipse(x, y, width / 2, width / 7, 0, 0, Math.PI * 2);
      ctx.fill();
    }

    /* Jungle tree standing at (x, y) on the ground. */
    drawTree(x, y, scale) {
      const ctx = this.ctx;
      const c = this.colors;
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(scale, scale);
      ctx.fillStyle = c.trunk;
      ctx.fillRect(-9, -120, 18, 120);
      ctx.fillStyle = c.leaves;
      [[0, -150, 52], [-34, -122, 36], [34, -122, 36], [0, -196, 36]].forEach(([cx, cy, r]) => {
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.restore();
    }

    /* Obstacle: a road STOP sign on a post, standing on the path. */
    drawStopSign(x, y, scale) {
      const ctx = this.ctx;
      const c = this.colors;
      this.shadow(x, y, ITEM_SIZE * 1.1 * scale);
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(scale, scale);
      ctx.fillStyle = c.pathEdge;
      ctx.fillRect(-4, -ITEM_SIZE * 0.9, 8, ITEM_SIZE * 0.9);
      ctx.translate(0, -ITEM_SIZE * 1.1);
      const octagon = (radius) => {
        ctx.beginPath();
        for (let i = 0; i < 8; i++) {
          const angle = Math.PI / 8 + (i * Math.PI) / 4;
          ctx.lineTo(radius * Math.cos(angle), radius * Math.sin(angle));
        }
        ctx.closePath();
      };
      const radius = ITEM_SIZE / 2 / Math.cos(Math.PI / 8);
      ctx.fillStyle = c.obstacleText;
      octagon(radius);
      ctx.fill();
      ctx.fillStyle = c.obstacle;
      octagon(radius - 4);
      ctx.fill();
      ctx.fillStyle = c.obstacleText;
      ctx.font = "800 21px 'Rethink Sans', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("STOP", 0, 1);
      ctx.restore();
    }

    /* Coin: gold disc with an inner ring and its value ("+10"), floating. */
    drawCoin(x, y, scale) {
      const ctx = this.ctx;
      const c = this.colors;
      const radius = ITEM_SIZE / 2.4;
      this.shadow(x, y, radius * 1.6 * scale);
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(scale, scale);
      ctx.translate(0, -radius - 18 - 6 * Math.sin(this.elapsed * 5));
      ctx.fillStyle = c.coin;
      ctx.strokeStyle = c.coinEdge;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(0, 0, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(0, 0, radius - 6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = c.coinEdge;
      ctx.font = "800 20px 'Rethink Sans', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(`+${this.settings.pointsPerCoin}`, 0, 1);
      ctx.restore();
    }

    /* The runner, seen from behind: body, head, swinging legs; a jump lifts
     * it in an arc over its shadow. */
    drawPlayer() {
      const ctx = this.ctx;
      const c = this.colors;
      const ground = this.project(this.playerX, 0);
      const jumping = this.elapsed < this.jumpUntil;
      let lift = 0;
      if (jumping) {
        const t = 1 - (this.jumpUntil - this.elapsed) / this.settings.jumpSeconds;
        lift = Math.sin(Math.PI * t) * JUMP_HEIGHT;
      }
      this.shadow(ground.x, ground.y, PLAYER_SIZE * (1 - lift / (JUMP_HEIGHT * 2.5)));
      // Blink while invulnerable after a hit.
      if (this.elapsed < this.invulnerableUntil && Math.floor(this.elapsed * 10) % 2 === 0) return;

      ctx.save();
      ctx.translate(ground.x, ground.y - lift);
      const stride = jumping ? 0.5 : Math.sin(this.elapsed * 14);
      // Legs
      ctx.strokeStyle = c.text;
      ctx.lineWidth = 12;
      ctx.lineCap = "round";
      [-1, 1].forEach((side) => {
        ctx.beginPath();
        ctx.moveTo(side * 12, -46);
        ctx.lineTo(side * 14, -8 - side * stride * 10);
        ctx.stroke();
      });
      // Body
      ctx.fillStyle = c.player;
      ctx.beginPath();
      ctx.roundRect(-PLAYER_SIZE / 3, -PLAYER_SIZE * 1.25, (PLAYER_SIZE * 2) / 3, PLAYER_SIZE * 0.75, 16);
      ctx.fill();
      // Arms
      ctx.strokeStyle = c.player;
      ctx.lineWidth = 11;
      [-1, 1].forEach((side) => {
        ctx.beginPath();
        ctx.moveTo(side * PLAYER_SIZE * 0.3, -PLAYER_SIZE * 1.12);
        ctx.lineTo(side * PLAYER_SIZE * 0.45, -PLAYER_SIZE * 0.7 + side * stride * 10);
        ctx.stroke();
      });
      // Head (back of it) with a cap
      ctx.fillStyle = c.skin;
      ctx.beginPath();
      ctx.arc(0, -PLAYER_SIZE * 1.48, PLAYER_SIZE * 0.26, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = c.jump;
      ctx.beginPath();
      ctx.arc(0, -PLAYER_SIZE * 1.52, PLAYER_SIZE * 0.26, Math.PI, Math.PI * 2);
      ctx.fill();
      if (jumping) {
        ctx.strokeStyle = c.jump;
        ctx.lineWidth = 5;
        ctx.beginPath();
        ctx.arc(0, -PLAYER_SIZE * 0.8, PLAYER_SIZE * 1.05, Math.PI * 1.15, Math.PI * 1.85);
        ctx.stroke();
      }
      ctx.restore();
    }
  }

  window.RunnerGame = RunnerGame;
})();
