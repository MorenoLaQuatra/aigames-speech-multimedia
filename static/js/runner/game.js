/* RunnerGame: a slow, forgiving 3-lane top-down runner on a <canvas>.
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

    /* ----------------------------------------------------------- drawing */

    draw() {
      const ctx = this.ctx;
      const c = this.colors;
      ctx.fillStyle = c.bg;
      ctx.fillRect(0, 0, WIDTH, HEIGHT);

      // Scrolling lane dividers give a sense of speed.
      ctx.strokeStyle = c.lane;
      ctx.lineWidth = 4;
      ctx.setLineDash([30, 30]);
      ctx.lineDashOffset = -((this.elapsed * this.speed) % 60);
      [200, 400].forEach((x) => {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, HEIGHT);
        ctx.stroke();
      });
      ctx.setLineDash([]);

      this.items.forEach((item) => {
        const x = LANES[item.lane];
        if (item.type === "obstacle") this.drawStopSign(x, item.y);
        else this.drawCoin(x, item.y);
      });

      this.drawPlayer();

      if (this.flash && this.elapsed < this.flash.until) {
        ctx.fillStyle = c.text;
        ctx.font = "800 64px 'Rethink Sans', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "alphabetic";
        ctx.fillText(ARROWS[this.flash.name], this.playerX, PLAYER_Y - PLAYER_SIZE);
      }
    }

    /* Obstacle: a road STOP sign (red octagon, white rim and lettering). */
    drawStopSign(x, y) {
      const ctx = this.ctx;
      const c = this.colors;
      const octagon = (radius) => {
        ctx.beginPath();
        for (let i = 0; i < 8; i++) {
          const angle = Math.PI / 8 + (i * Math.PI) / 4;
          ctx.lineTo(x + radius * Math.cos(angle), y + radius * Math.sin(angle));
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
      ctx.fillText("STOP", x, y + 1);
    }

    /* Coin: gold disc with an inner ring and its value ("+10"). */
    drawCoin(x, y) {
      const ctx = this.ctx;
      const c = this.colors;
      const radius = ITEM_SIZE / 2.4;
      ctx.fillStyle = c.coin;
      ctx.strokeStyle = c.coinEdge;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(x, y, radius - 6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = c.coinEdge;
      ctx.font = "800 20px 'Rethink Sans', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(`+${this.settings.pointsPerCoin}`, x, y + 1);
    }

    drawPlayer() {
      const ctx = this.ctx;
      const c = this.colors;
      const jumping = this.elapsed < this.jumpUntil;
      const invulnerable = this.elapsed < this.invulnerableUntil;
      // Blink while invulnerable after a hit.
      if (invulnerable && Math.floor(this.elapsed * 10) % 2 === 0) return;
      const size = jumping ? PLAYER_SIZE * 1.3 : PLAYER_SIZE;
      if (jumping) {
        ctx.strokeStyle = c.jump;
        ctx.lineWidth = 8;
        ctx.beginPath();
        ctx.arc(this.playerX, PLAYER_Y, size / 2 + 8, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.fillStyle = c.player;
      ctx.beginPath();
      ctx.arc(this.playerX, PLAYER_Y, size / 2, 0, Math.PI * 2);
      ctx.fill();
      // Simple face so it reads as "the runner", not a dot.
      ctx.fillStyle = c.playerText;
      ctx.beginPath();
      ctx.arc(this.playerX - size * 0.15, PLAYER_Y - size * 0.08, size * 0.07, 0, Math.PI * 2);
      ctx.arc(this.playerX + size * 0.15, PLAYER_Y - size * 0.08, size * 0.07, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  window.RunnerGame = RunnerGame;
})();
