import { Application, Ticker } from 'pixi.js';
import '@pixi/unsafe-eval';
import { Live2DModel } from 'pixi-live2d-display/cubism4';

Live2DModel.registerTicker(Ticker);

(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const mode = params.get('mode') === 'control' ? 'control' : 'avatar';
  const avatarView = document.getElementById('avatar-view');
  const controlView = document.getElementById('control-view');
  const clientId = `${mode}-${crypto.randomUUID()}`;
  const sessionId = 'desktop-local';
  let appConfig = null;
  let socket = null;
  let avatarController = null;

  const TAP_MIN_DURATION_MS = 40;
  const TAP_MAX_DURATION_MS = 350;
  const TAP_MAX_DISTANCE_PX = 3;
  const DRAG_START_DISTANCE_PX = 6;
  const SLOW_DRAG_DELAY_MS = 160;
  const DEFAULT_TOUCH_COOLDOWN_MS = 1200;

  class DesktopSocket {
    constructor(config, onEvent) {
      this.config = config;
      this.onEvent = onEvent;
      this.ws = null;
      this.pending = [];
      this.reconnectDelay = 500;
      this.closed = false;
      this.lastSeq = Number(localStorage.getItem(`shion-seq-${mode}`) || 0);
      this.heartbeat = null;
    }

    connect() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = new URL(`${protocol}//${location.host}/ws/desktop`);
      url.searchParams.set('client_id', clientId);
      url.searchParams.set('token', this.config.token);
      url.searchParams.set('after_seq', String(this.lastSeq));
      this.ws = new WebSocket(url);
      this.ws.binaryType = 'arraybuffer';
      this.ws.addEventListener('open', () => {
        this.reconnectDelay = 500;
        this.send('client.hello', { mode, capabilities: ['text', 'audio', 'touch', 'behaviour'] });
        for (const item of this.pending.splice(0)) this.ws.send(item);
        clearInterval(this.heartbeat);
        this.heartbeat = setInterval(() => this.send('ping', {}), 15000);
        this.onEvent({ type: 'connection.open', payload: {} });
      });
      this.ws.addEventListener('message', (message) => {
        if (typeof message.data !== 'string') return;
        try {
          const event = JSON.parse(message.data);
          if (event.seq) {
            this.lastSeq = Math.max(this.lastSeq, Number(event.seq));
            localStorage.setItem(`shion-seq-${mode}`, String(this.lastSeq));
          }
          this.onEvent(event);
        } catch (error) {
          console.error('Invalid desktop event', error);
        }
      });
      this.ws.addEventListener('close', () => {
        clearInterval(this.heartbeat);
        this.onEvent({ type: 'connection.closed', payload: {} });
        if (!this.closed) {
          setTimeout(() => this.connect(), this.reconnectDelay);
          this.reconnectDelay = Math.min(this.reconnectDelay * 1.8, 10000);
        }
      });
      this.ws.addEventListener('error', () => this.ws.close());
    }

    envelope(type, payload) {
      return {
        v: 1,
        type,
        event_id: crypto.randomUUID(),
        trace_id: crypto.randomUUID(),
        session_id: sessionId,
        timestamp: new Date().toISOString(),
        payload,
      };
    }

    send(type, payload, options = {}) {
      const event = this.envelope(type, payload);
      if (options.traceId) event.trace_id = options.traceId;
      const raw = JSON.stringify(event);
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(raw);
      else if (options.queueIfOffline !== false) this.pending.push(raw);
      else return null;
      return event;
    }

    sendBinary(data) {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        throw new Error('WebSocket 尚未连接');
      }
      this.ws.send(data);
    }
  }

  class AvatarController {
    constructor(config) {
      this.config = config;
      this.canvas = document.getElementById('live2d-canvas');
      this.status = document.getElementById('avatar-status');
      this.bubble = document.getElementById('speech-bubble');
      this.model = null;
      this.resolveModelReady = null;
      this.modelReady = new Promise((resolve) => {
        this.resolveModelReady = resolve;
      });
      this.pixi = null;
      this.expressionTimer = null;
      this.currentPriority = -1;
      this.bubbleTimer = null;
      this.drag = null;
      this.dragFrame = null;
      this.pendingDragPoint = null;
      this.lastTouchSentAt = -Infinity;
      this.passthrough = null;
      this.audio = null;
      this.audioContext = null;
      this.analyser = null;
      this.audioSamples = null;
      this.activeAudioFinish = null;
      this.activeAudioTimer = null;
      this.behaviourQueue = [];
      this.processingBehaviours = false;
      this.cancelBehaviourWait = null;
      this.requestedResize = false;
      this.installInteraction();
    }

    async load() {
      if (!globalThis.Live2DCubismCore) {
        this.setStatus('请将官方 live2dcubismcore.min.js 放入 desktop/vendor');
        window.shionDesktop?.setMousePassthrough(false);
        this.markModelReady(false);
        return;
      }
      try {
        this.pixi = new Application({
          view: this.canvas,
          resizeTo: window,
          transparent: true,
          backgroundAlpha: 0,
          antialias: true,
          autoDensity: true,
          resolution: Math.min(devicePixelRatio || 1, 2),
        });
        const gl = this.pixi.renderer.gl;
        const maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
        const requiredTextureSize = Math.max(
          0,
          ...(this.config.textures || []).flatMap((item) => [item.width, item.height]),
        );
        if (requiredTextureSize > maxTextureSize) {
          throw new Error(
            `GPU 最大纹理尺寸为 ${maxTextureSize}，模型需要 ${requiredTextureSize}`,
          );
        }
        this.model = await Live2DModel.from(this.config.model_url, {
          autoHitTest: false,
          autoFocus: false,
        });
        this.ensureCubismCoreCompatibility();
        this.installPersistentParameters();
        this.model.anchor.set(0.5, 0.5);
        this.pixi.stage.addChild(this.model);
        this.fitModel();
        addEventListener('resize', () => this.fitModel());
        this.pixi.ticker.add(() => this.updateLipSync());
        this.setStatus('');
        window.shionDesktop?.setMousePassthrough(true);
        this.markModelReady(true);
      } catch (error) {
        console.error(error);
        const message = error?.message || String(error);
        this.setStatus(`模型加载失败：${message}`);
        socket?.send('client.error', {
          stage: 'model.load',
          name: error?.name || 'Error',
          message,
          stack: error?.stack || '',
          model_url: this.config.model_url,
          core_version: globalThis.Live2DCubismCore?.Version?.csmGetVersion?.() || null,
        });
        window.shionDesktop?.setMousePassthrough(false);
        this.markModelReady(false);
      }
    }

    markModelReady(loaded) {
      this.resolveModelReady?.(loaded);
      this.resolveModelReady = null;
    }

    ensureCubismCoreCompatibility() {
      // Newer Cubism Core releases moved the combined render-order array from
      // `model.drawables.renderOrders` to `model.renderOrders`. The Cubism 4
      // framework bundled by pixi-live2d-display still reads the old field,
      // so expose a drawable-only view before Pixi renders the first frame.
      const coreModel = this.model?.internalModel?.coreModel?._model;
      const drawables = coreModel?.drawables;
      if (!drawables?.renderOrders && coreModel?.renderOrders) {
        drawables.renderOrders = coreModel.renderOrders.subarray(
          0,
          Number(drawables.count) || 0,
        );
      }
    }

    installPersistentParameters() {
      const entries = Object.entries(this.config.persistent_parameters || {})
        .map(([id, value]) => [String(id), Number(value)])
        .filter(([id, value]) => id && Number.isFinite(value));
      const internalModel = this.model?.internalModel;
      const coreModel = internalModel?.coreModel;
      if (!entries.length || !internalModel || !coreModel) return;

      const apply = () => {
        for (const [id, value] of entries) {
          try {
            coreModel.setParameterValueById(id, value);
          } catch (_) {}
        }
      };
      apply();
      internalModel.on('beforeModelUpdate', apply);
    }

    fitModel() {
      if (!this.model) return;
      const sourceWidth = Math.max(this.model.width / Math.max(this.model.scale.x, 0.001), 1);
      const sourceHeight = Math.max(this.model.height / Math.max(this.model.scale.y, 0.001), 1);
      if (!this.requestedResize) {
        this.requestedResize = true;
        const desiredHeight = Math.max(560, Math.min(innerHeight, 820));
        const desiredWidth = Math.max(
          300,
          Math.min(720, Math.round(desiredHeight * sourceWidth / sourceHeight * 1.12)),
        );
        if (Math.abs(desiredWidth - innerWidth) > 20) {
          window.shionDesktop?.resizeAvatar({ width: desiredWidth, height: desiredHeight });
        }
      }
      const scale = Math.min(innerWidth * 0.96 / sourceWidth, innerHeight * 0.98 / sourceHeight);
      this.model.scale.set(scale);
      this.model.position.set(innerWidth / 2, innerHeight / 2 + innerHeight * 0.02);
    }

    setStatus(text) {
      this.status.textContent = text;
      this.status.classList.toggle('hidden', !text);
    }

    applyBehaviour(payload) {
      const priority = Number(payload.priority || 0);
      if (payload.interrupt || (this.processingBehaviours && priority > this.currentPriority)) {
        this.behaviourQueue.length = 0;
        this.cancelCurrentPresentation();
        this.behaviourQueue.unshift(payload);
      } else {
        this.behaviourQueue.push(payload);
      }
      void this.drainBehaviourQueue();
    }

    async drainBehaviourQueue() {
      if (this.processingBehaviours) return;
      this.processingBehaviours = true;
      try {
        while (this.behaviourQueue.length) {
          const payload = this.behaviourQueue.shift();
          await this.presentBehaviour(payload);
        }
      } finally {
        this.processingBehaviours = false;
      }
    }

    async presentBehaviour(payload) {
      if (!this.model) await this.modelReady;
      const configuredDuration = Number(payload.duration_ms);
      const duration = Number.isFinite(configuredDuration)
        ? Math.max(0, configuredDuration)
        : 2400;
      const hasAudio = Boolean(payload.audio_url);
      this.showSpeech(payload.text, hasAudio ? 0 : duration);
      this.applyExpression({ ...payload, duration_ms: 0 });
      if (hasAudio) await this.playAudio(payload.audio_url);
      else if (duration > 0) await this.waitForPresentation(duration);
      this.resetExpression();
      this.hideSpeech();
    }

    waitForPresentation(duration) {
      return new Promise((resolve) => {
        let timer = null;
        const finish = () => {
          if (timer !== null) clearTimeout(timer);
          if (this.cancelBehaviourWait === finish) this.cancelBehaviourWait = null;
          resolve();
        };
        this.cancelBehaviourWait = finish;
        timer = setTimeout(finish, duration);
      });
    }

    cancelCurrentPresentation() {
      const cancelWait = this.cancelBehaviourWait;
      this.cancelBehaviourWait = null;
      cancelWait?.();
      this.stopAudio();
    }

    applyExpression(payload) {
      if (!this.model) return;
      clearTimeout(this.expressionTimer);
      this.currentPriority = Number(payload.priority || 0);
      const requested = [...(payload.overlays || []), payload.base].filter(Boolean).pop() || 'normal';
      const expressionFile = this.config.expression_map[requested] || requested;
      const expressionName = expressionFile
        ? String(expressionFile).replace(/\.exp3\.json$/i, '')
        : null;
      try {
        if (!expressionName || requested === 'normal') this.resetExpression();
        else this.model.expression(expressionName).catch?.((error) => {
          console.warn('Expression failed', requested, error);
        });
        if (payload.motion && this.config.motions.length) {
          this.model.motion(String(payload.motion), 0, 3).catch?.(() => {});
        }
      } catch (error) {
        console.warn('Expression failed', requested, error);
      }
      const configuredDuration = Number(payload.duration_ms);
      const duration = Number.isFinite(configuredDuration)
        ? Math.max(0, configuredDuration)
        : 2400;
      if (duration > 0) this.expressionTimer = setTimeout(() => this.resetExpression(), duration);
    }

    resetExpression() {
      clearTimeout(this.expressionTimer);
      this.expressionTimer = null;
      const manager = this.model?.internalModel?.motionManager?.expressionManager;
      manager?.stopAllExpressions?.();
      if (manager?.defaultExpression) manager.currentExpression = manager.defaultExpression;
      manager?.resetExpression?.();
      this.currentPriority = -1;
    }

    showSpeech(text, duration = 5000) {
      if (!text) return;
      clearTimeout(this.bubbleTimer);
      this.bubble.textContent = text;
      this.bubble.classList.remove('hidden');
      if (duration > 0) {
        this.bubbleTimer = setTimeout(() => this.bubble.classList.add('hidden'), duration);
      }
    }

    hideSpeech() {
      clearTimeout(this.bubbleTimer);
      this.bubbleTimer = null;
      this.bubble.classList.add('hidden');
    }

    async playAudio(url) {
      try {
        this.stopAudio();
        this.audio = new Audio(url);
        const audio = this.audio;
        this.audioContext = new AudioContext();
        const source = this.audioContext.createMediaElementSource(audio);
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;
        this.audioSamples = new Uint8Array(this.analyser.fftSize);
        source.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);
        const finished = new Promise((resolve) => {
          this.activeAudioFinish = resolve;
        });
        const armAudioTimeout = (durationMs) => {
          clearTimeout(this.activeAudioTimer);
          this.activeAudioTimer = setTimeout(
            () => this.stopAudio(),
            Math.max(3000, durationMs),
          );
        };
        // MediaElement `ended` can be throttled or omitted for a background
        // desktop window. Never let one audio item deadlock the visual queue.
        armAudioTimeout(120000);
        audio.addEventListener('loadedmetadata', () => {
          if (this.audio !== audio) return;
          const durationMs = Number(audio.duration) * 1000;
          if (Number.isFinite(durationMs) && durationMs > 0) {
            armAudioTimeout(durationMs + 1500);
          }
        }, { once: true });
        audio.addEventListener('ended', () => {
          if (this.audio === audio) this.stopAudio();
        }, { once: true });
        audio.addEventListener('error', () => {
          if (this.audio === audio) this.stopAudio();
        }, { once: true });
        const startTasks = [audio.play()];
        if (this.audioContext.state === 'suspended') {
          startTasks.push(this.audioContext.resume());
        }
        // Starting WebAudio can remain pending in a background window. Race
        // startup with completion/watchdog so the presentation queue always
        // makes progress.
        await Promise.race([Promise.all(startTasks), finished]);
        await finished;
      } catch (error) {
        console.warn('Audio playback failed', error);
        this.stopAudio();
      }
    }

    updateLipSync() {
      if (!this.analyser || !this.audioSamples || !this.model) return;
      this.analyser.getByteTimeDomainData(this.audioSamples);
      let power = 0;
      for (const value of this.audioSamples) {
        const sample = (value - 128) / 128;
        power += sample * sample;
      }
      const mouth = Math.min(1, Math.sqrt(power / this.audioSamples.length) * 5.5);
      try {
        this.model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', mouth);
      } catch (_) {}
    }

    stopAudio() {
      if (this.audio) {
        this.audio.pause();
        this.audio.src = '';
      }
      this.audio = null;
      this.analyser = null;
      this.audioSamples = null;
      this.audioContext?.close().catch(() => {});
      this.audioContext = null;
      clearTimeout(this.activeAudioTimer);
      this.activeAudioTimer = null;
      const finish = this.activeAudioFinish;
      this.activeAudioFinish = null;
      finish?.();
      try {
        this.model?.internalModel?.coreModel?.setParameterValueById('ParamMouthOpenY', 0);
      } catch (_) {}
    }

    installInteraction() {
      this.canvas.addEventListener('pointermove', (event) => {
        const hit = this.hitModel(event.clientX, event.clientY);
        this.setPassthrough(!hit && !this.drag);
        if (!this.drag || event.pointerId !== this.drag.pointerId) return;
        event.preventDefault();
        this.updateInteractionDistance(this.drag, event);
        if (!this.drag.moving && this.isDragIntent(this.drag)) this.startDragging(this.drag);
        if (this.drag.moving) this.queueDragMove(event.screenX, event.screenY);
      });
      this.canvas.addEventListener('pointerdown', (event) => {
        if (event.button !== 0 || !this.hitModel(event.clientX, event.clientY)) return;
        event.preventDefault();
        this.canvas.setPointerCapture(event.pointerId);
        this.drag = {
          pointerId: event.pointerId,
          startX: event.screenX,
          startY: event.screenY,
          clientX: event.clientX,
          clientY: event.clientY,
          startedAt: performance.now(),
          maxDistance: 0,
          moving: false,
        };
      });
      this.canvas.addEventListener('pointerup', (event) => {
        if (!this.drag || event.pointerId !== this.drag.pointerId) return;
        event.preventDefault();
        const interaction = this.drag;
        this.updateInteractionDistance(interaction, event);
        const duration = Math.round(performance.now() - interaction.startedAt);
        const dragIntent = interaction.moving || this.isDragIntent(interaction);
        const releasedOnModel = this.hitModel(event.clientX, event.clientY);
        this.drag = null;
        if (this.canvas.hasPointerCapture(event.pointerId)) {
          this.canvas.releasePointerCapture(event.pointerId);
        }

        if (interaction.moving) {
          this.flushDragMove(event.screenX, event.screenY);
          window.shionDesktop?.endDrag();
        } else {
          this.cancelDragMove();
        }

        const isTap = !dragIntent
          && releasedOnModel
          && interaction.maxDistance <= TAP_MAX_DISTANCE_PX
          && duration >= TAP_MIN_DURATION_MS
          && duration <= TAP_MAX_DURATION_MS;
        if (isTap) {
          const region = this.touchRegion(interaction.clientX, interaction.clientY);
          this.localTouchReaction(region);
          const now = performance.now();
          const configuredCooldown = Number(this.config.touch_cooldown_ms);
          const cooldown = Number.isFinite(configuredCooldown)
            ? Math.max(0, configuredCooldown)
            : DEFAULT_TOUCH_COOLDOWN_MS;
          if (now - this.lastTouchSentAt >= cooldown) {
            const sent = socket?.send('input.touch', {
              region,
              gesture: 'tap',
              duration_ms: duration,
            }, { queueIfOffline: false });
            if (sent) this.lastTouchSentAt = now;
          }
        }
      });
      this.canvas.addEventListener('pointercancel', (event) => this.cancelInteraction(event));
      this.canvas.addEventListener('lostpointercapture', (event) => this.cancelInteraction(event));
      addEventListener('blur', () => this.cancelInteraction());
      this.canvas.addEventListener('dblclick', () => window.shionDesktop?.showControls());
      this.canvas.addEventListener('contextmenu', (event) => {
        event.preventDefault();
        window.shionDesktop?.showControls();
      });
    }

    updateInteractionDistance(interaction, event) {
      const distance = Math.hypot(
        event.screenX - interaction.startX,
        event.screenY - interaction.startY,
      );
      interaction.maxDistance = Math.max(interaction.maxDistance, distance);
    }

    isDragIntent(interaction) {
      const duration = performance.now() - interaction.startedAt;
      return interaction.maxDistance >= DRAG_START_DISTANCE_PX
        || (duration >= SLOW_DRAG_DELAY_MS && interaction.maxDistance > TAP_MAX_DISTANCE_PX);
    }

    startDragging(interaction) {
      interaction.moving = true;
      window.shionDesktop?.startDrag({ x: interaction.startX, y: interaction.startY });
    }

    queueDragMove(x, y) {
      this.pendingDragPoint = { x, y };
      if (this.dragFrame !== null) return;
      this.dragFrame = requestAnimationFrame(() => {
        this.dragFrame = null;
        const point = this.pendingDragPoint;
        this.pendingDragPoint = null;
        if (point && this.drag?.moving) window.shionDesktop?.moveDrag(point);
      });
    }

    flushDragMove(x, y) {
      this.cancelDragMove();
      window.shionDesktop?.moveDrag({ x, y });
    }

    cancelDragMove() {
      if (this.dragFrame !== null) cancelAnimationFrame(this.dragFrame);
      this.dragFrame = null;
      this.pendingDragPoint = null;
    }

    cancelInteraction(event) {
      if (!this.drag || (event && event.pointerId !== this.drag.pointerId)) return;
      const wasMoving = this.drag.moving;
      this.drag = null;
      this.cancelDragMove();
      if (wasMoving) window.shionDesktop?.endDrag();
    }

    hitModel(x, y) {
      if (!this.model) return false;
      const bounds = this.model.getBounds();
      if (!bounds.contains(x, y)) return false;
      const nx = (x - bounds.x) / bounds.width;
      const ny = (y - bounds.y) / bounds.height;
      const head = ((nx - 0.5) / 0.49) ** 2 + ((ny - 0.31) / 0.33) ** 2 <= 1;
      const bodyHalfWidth = 0.27 + Math.max(0, ny - 0.42) * 0.42;
      const body = ny >= 0.35 && ny <= 1 && Math.abs(nx - 0.5) <= bodyHalfWidth;
      return head || body;
    }

    touchRegion(x, y) {
      if (!this.model) return 'body';
      const bounds = this.model.getBounds();
      const ny = (y - bounds.y) / bounds.height;
      if (ny < 0.28) return 'head';
      if (ny < 0.55) return 'face';
      return 'body';
    }

    localTouchReaction(region) {
      const core = this.model?.internalModel?.coreModel;
      if (!core) return;
      try {
        core.addParameterValueById('ParamAngleZ', region === 'head' ? 7 : 3, 0.8);
      } catch (_) {}
    }

    setPassthrough(ignore) {
      if (this.passthrough === ignore) return;
      this.passthrough = ignore;
      window.shionDesktop?.setMousePassthrough(ignore);
    }
  }

  function setupControl() {
    const state = document.getElementById('connection-state');
    const messages = document.getElementById('messages');
    const form = document.getElementById('message-form');
    const input = document.getElementById('message-input');
    const close = document.getElementById('close-controls');
    const recordButton = document.getElementById('record-button');
    const recordState = document.getElementById('record-state');
    const streaming = new Map();
    let recorder = null;
    let audioChunks = [];
    let recordStarted = 0;
    let audioId = '';
    let audioTrace = '';

    const append = (role, text) => {
      const item = document.createElement('div');
      item.className = `message ${role}`;
      item.textContent = text;
      messages.appendChild(item);
      messages.scrollTop = messages.scrollHeight;
      return item;
    };

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      append('user', text);
      socket?.send('input.text', { text, user_id: 'desktop-user' });
      input.value = '';
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    close.addEventListener('click', () => window.shionDesktop?.hideControls());

    const startRecording = async (event) => {
      event.preventDefault();
      if (recorder?.state === 'recording') return;
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
          ? 'audio/webm;codecs=opus' : 'audio/webm';
        recorder = new MediaRecorder(stream, { mimeType });
        audioChunks = [];
        audioId = crypto.randomUUID();
        audioTrace = crypto.randomUUID();
        recorder.addEventListener('dataavailable', (chunk) => {
          if (chunk.data.size) audioChunks.push(chunk.data);
        });
        recorder.addEventListener('stop', async () => {
          stream.getTracks().forEach((track) => track.stop());
          const duration = Math.round(performance.now() - recordStarted);
          const blob = new Blob(audioChunks, { type: recorder.mimeType });
          try {
            socket.send('input.audio.begin', {
              audio_id: audioId,
              mime_type: recorder.mimeType,
              user_id: 'desktop-user',
            }, { traceId: audioTrace });
            socket.sendBinary(await blob.arrayBuffer());
            socket.send('input.audio.end', {
              audio_id: audioId,
              duration_ms: duration,
            }, { traceId: audioTrace });
            setRecordState(appConfig.asr_enabled ? '正在识别语音…' : '语音已发送（ASR 未配置）');
          } catch (error) {
            setRecordState(error.message);
          }
        });
        recorder.start(250);
        recordStarted = performance.now();
        recordButton.classList.add('recording');
        recordButton.textContent = '松开发送';
        setRecordState('正在录音…');
      } catch (error) {
        setRecordState(`无法录音：${error.message}`);
      }
    };
    const stopRecording = (event) => {
      event.preventDefault();
      if (recorder?.state === 'recording') recorder.stop();
      recordButton.classList.remove('recording');
      recordButton.textContent = '按住说话';
    };
    recordButton.addEventListener('pointerdown', startRecording);
    recordButton.addEventListener('pointerup', stopRecording);
    recordButton.addEventListener('pointercancel', stopRecording);
    recordButton.addEventListener('pointerleave', (event) => {
      if (event.buttons) stopRecording(event);
    });

    function setRecordState(text) {
      recordState.textContent = text;
      recordState.classList.toggle('hidden', !text);
    }

    return (event) => {
      if (event.type === 'connection.open') state.textContent = '已连接';
      if (event.type === 'connection.closed') state.textContent = '正在重连';
      if (event.type === 'agent.delta') {
        const key = event.trace_id || 'current';
        let item = streaming.get(key);
        if (!item) {
          item = append('agent', '');
          streaming.set(key, item);
        }
        item.textContent += event.payload.content || '';
        messages.scrollTop = messages.scrollHeight;
      }
      if (event.type === 'agent.done') streaming.delete(event.trace_id || 'current');
      if (event.type === 'input.transcribing') setRecordState('正在识别语音…');
      if (event.type === 'input.accepted') setRecordState('');
      if (event.type === 'error') {
        setRecordState(event.payload.message || event.payload.content || '发生错误');
      }
    };
  }

  async function boot() {
    try {
      appConfig = await fetch('/api/config').then((response) => {
        if (!response.ok) throw new Error(`配置加载失败：${response.status}`);
        return response.json();
      });
      let controlEventHandler = null;
      if (mode === 'avatar') {
        avatarView.classList.remove('hidden');
        avatarController = new AvatarController(appConfig);
      } else {
        controlView.classList.remove('hidden');
        controlEventHandler = setupControl();
      }
      socket = new DesktopSocket(appConfig, (event) => {
        if (mode === 'avatar' && event.type === 'behaviour.apply') {
          avatarController?.applyBehaviour(event.payload);
        }
        controlEventHandler?.(event);
      });
      socket.connect();
      if (mode === 'avatar') await avatarController.load();
    } catch (error) {
      console.error(error);
      document.getElementById('avatar-status').textContent = error.message;
      document.getElementById('avatar-status').classList.remove('hidden');
    }
  }

  boot();
})();
