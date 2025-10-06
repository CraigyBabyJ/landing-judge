/*
  Landing Judge Overlay (1080x1920 portrait)
  - Receives events via SSE: score, level, quote, audio URL, effects
  - Fixed client-side banner visibility duration (DEFAULT_MS)
  - Audio effects graph (Web Audio) with optional noise beds
  - Overlay shows the quote text and animated score; `message` is for API/logs
*/
(function () {
  // Global TTS flag propagated from server settings
  let ttsEnabled = true;
  const $ = (id) => document.getElementById(id);

  const display = $('number-display');
  const voteScore = $('vote-score');
  const scoreFraction = display.querySelector('.score-fraction');
  const quoteDisplay = $('quote-display');
  const quoteAudio = $('quote-audio');
  // Removed sound unlock prompt and state; OBS handles autoplay without clicks
  // Web Audio graph for effects
  let audioCtx = null;
  let sourceNode = null;
  let dryGain = null;
  let wetGain = null;
  let wetSum = null;
  let serialGain = null;
  let hpFilter = null;
  let lpFilter = null;
  let driveShaper = null;
  let compressor = null;
  let convolver = null;
  let convolverGain = null;
  let reverbLp = null;
  let delayNode = null;
  let feedbackGain = null;
  let fbLpFilter = null;
  let slapGain = null;
  let multiTapDelays = [];
  let multiTapGains = [];
  let chorusDelay = null;
  let chorusLfo = null;
  let chorusLfoGain = null;
  let chorusGain = null;
  let leftDelay = null;
  let rightDelay = null;
  let leftPan = null;
  let rightPan = null;
  let widenerGain = null;
  let noiseGain = null;
  let radioNoiseHp = null;
  let radioNoiseLp = null;
  let radioNoiseGain = null;
  let windNoiseGain = null;
  let noiseSource = null;
  let staticEnabled = false;
  let currentPreset = 'none';
  let staticNoiseLevel = 0.02;
  let radioNoiseLevel = 0.0;
  let windNoiseLevel = 0.0;

  function initAudioGraph() {
    if (audioCtx) return;
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      try { audioCtx.resume().catch(() => {}); } catch (e) {}
      sourceNode = audioCtx.createMediaElementSource(quoteAudio);
      // Core mix
      dryGain = audioCtx.createGain();
      wetGain = audioCtx.createGain();
      wetSum = audioCtx.createGain();
      serialGain = audioCtx.createGain();

      // Core processing blocks
      hpFilter = audioCtx.createBiquadFilter(); hpFilter.type = 'highpass';
      lpFilter = audioCtx.createBiquadFilter(); lpFilter.type = 'lowpass';
      driveShaper = audioCtx.createWaveShaper(); driveShaper.oversample = '2x';
      compressor = audioCtx.createDynamicsCompressor();

      // Reverb send path
      convolver = audioCtx.createConvolver();
      convolverGain = audioCtx.createGain(); convolverGain.gain.value = 0.0;
      reverbLp = audioCtx.createBiquadFilter(); reverbLp.type = 'lowpass'; reverbLp.frequency.value = 20000;

      // Slapback delay with feedback (feedback loop includes LPF)
      delayNode = audioCtx.createDelay(2.0);
      feedbackGain = audioCtx.createGain(); feedbackGain.gain.value = 0.0;
      fbLpFilter = audioCtx.createBiquadFilter(); fbLpFilter.type = 'lowpass'; fbLpFilter.frequency.value = 20000;
      slapGain = audioCtx.createGain(); slapGain.gain.value = 0.0;

      // Multi-tap early reflections
      multiTapDelays = [audioCtx.createDelay(0.5), audioCtx.createDelay(0.5), audioCtx.createDelay(0.5), audioCtx.createDelay(0.5)];
      multiTapGains = [audioCtx.createGain(), audioCtx.createGain(), audioCtx.createGain(), audioCtx.createGain()];
      multiTapGains.forEach(g => g.gain.value = 0.0);

      // Chorus
      chorusDelay = audioCtx.createDelay(0.1);
      chorusLfo = audioCtx.createOscillator(); chorusLfo.type = 'sine';
      chorusLfoGain = audioCtx.createGain(); chorusLfoGain.gain.value = 0.0;
      chorusGain = audioCtx.createGain(); chorusGain.gain.value = 0.0;
      chorusLfo.connect(chorusLfoGain);
      chorusLfoGain.connect(chorusDelay.delayTime);
      try { chorusLfo.start(); } catch (e) {}

      // Stereo widener (Haas)
      leftDelay = audioCtx.createDelay(0.05);
      rightDelay = audioCtx.createDelay(0.05);
      leftPan = audioCtx.createStereoPanner(); leftPan.pan.value = -1;
      rightPan = audioCtx.createStereoPanner(); rightPan.pan.value = 1;
      widenerGain = audioCtx.createGain(); widenerGain.gain.value = 0.0;

      // Noise sources
      noiseGain = audioCtx.createGain(); noiseGain.gain.value = 0.0; // static
      radioNoiseHp = audioCtx.createBiquadFilter(); radioNoiseHp.type = 'highpass'; radioNoiseHp.frequency.value = 2000;
      radioNoiseLp = audioCtx.createBiquadFilter(); radioNoiseLp.type = 'lowpass'; radioNoiseLp.frequency.value = 6000;
      radioNoiseGain = audioCtx.createGain(); radioNoiseGain.gain.value = 0.0;
      windNoiseGain = audioCtx.createGain(); windNoiseGain.gain.value = 0.0;
      const bufferSize = 2 * audioCtx.sampleRate;
      const noiseBuffer = audioCtx.createBuffer(1, bufferSize, audioCtx.sampleRate);
      const data = noiseBuffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) data[i] = (Math.random() * 2 - 1);
      noiseSource = audioCtx.createBufferSource();
      noiseSource.buffer = noiseBuffer; noiseSource.loop = true;
      // Route noise to three beds: plain static, radio hiss band-limited, wind (low overall)
      noiseSource.connect(noiseGain);
      noiseSource.connect(radioNoiseHp); radioNoiseHp.connect(radioNoiseLp); radioNoiseLp.connect(radioNoiseGain);
      noiseSource.connect(windNoiseGain);
      noiseSource.start();

      // Build serial base: source -> hp -> lp -> drive -> compressor -> serialGain
      sourceNode.connect(hpFilter);
      hpFilter.connect(lpFilter);
      lpFilter.connect(driveShaper);
      driveShaper.connect(compressor);
      compressor.connect(serialGain);

      // Connect sends to wetSum
      // Reverb: serial -> convolver -> LPF -> convolverGain -> wetSum
      serialGain.connect(convolver);
      convolver.connect(reverbLp);
      reverbLp.connect(convolverGain);
      convolverGain.connect(wetSum);
      // Slapback: serial -> delay -> slapGain -> wetSum (feedback loop)
      serialGain.connect(delayNode);
      delayNode.connect(slapGain);
      slapGain.connect(wetSum);
      delayNode.connect(feedbackGain);
      feedbackGain.connect(fbLpFilter);
      fbLpFilter.connect(delayNode);
      // Multi-taps
      multiTapDelays.forEach((d, i) => { serialGain.connect(d); d.connect(multiTapGains[i]); multiTapGains[i].connect(wetSum); });
      // Chorus
      serialGain.connect(chorusDelay);
      chorusDelay.connect(chorusGain);
      chorusGain.connect(wetSum);
      // Widener
      serialGain.connect(leftDelay); leftDelay.connect(leftPan); leftPan.connect(widenerGain);
      serialGain.connect(rightDelay); rightDelay.connect(rightPan); rightPan.connect(widenerGain);
      widenerGain.connect(wetSum);

      // Master: dry + wet + noise beds -> destination
      sourceNode.connect(dryGain);
      dryGain.connect(audioCtx.destination);
      wetSum.connect(wetGain);
      wetGain.connect(audioCtx.destination);
      noiseGain.connect(audioCtx.destination);
      radioNoiseGain.connect(audioCtx.destination);
      windNoiseGain.connect(audioCtx.destination);

      // Defaults
      dryGain.gain.value = 1.0; wetGain.gain.value = 0.0;
      // Only play noise beds during actual audio playback
      quoteAudio.addEventListener('play', () => {
        // If TTS is disabled for any reason, immediately kill playback
        if (!ttsEnabled) {
          try {
            quoteAudio.pause();
            quoteAudio.currentTime = 0;
            quoteAudio.src = '';
          } catch (e) { /* ignore */ }
          try {
            noiseGain.gain.value = 0.0;
            radioNoiseGain.gain.value = 0.0;
            windNoiseGain.gain.value = 0.0;
          } catch (e) { /* ignore */ }
          return;
        }
        try {
          // Only add plain static when 'None' preset is active
          noiseGain.gain.value = (staticEnabled && currentPreset === 'none') ? (staticNoiseLevel || 0.02) : 0.0;
          // Gate radio hiss and wind noise to their matching presets
          radioNoiseGain.gain.value = (currentPreset === 'atc_radio') ? (radioNoiseLevel || 0.0) : 0.0;
          windNoiseGain.gain.value = (currentPreset === 'apron_outdoor') ? (windNoiseLevel || 0.0) : 0.0;
        } catch (e) {}
      });
      const stopNoiseBeds = () => {
        try {
          noiseGain.gain.value = 0.0;
          radioNoiseGain.gain.value = 0.0;
          windNoiseGain.gain.value = 0.0;
        } catch (e) {}
      };
      quoteAudio.addEventListener('pause', stopNoiseBeds);
      quoteAudio.addEventListener('ended', stopNoiseBeds);
    } catch (e) {
      console.warn('Audio effects not initialized:', e);
    }
  }

  // Removed unlock handlers; browsers may require muted autoplay, which is handled in play() logic

  function makeSoftClipCurve(amount = 1.5) {
    const samples = 1024;
    const curve = new Float32Array(samples);
    const k = amount;
    for (let i = 0; i < samples; i++) {
      const x = (i / (samples - 1)) * 2 - 1;
      curve[i] = Math.tanh(k * x) / Math.tanh(k);
    }
    return curve;
  }

  function makeImpulseResponse(seconds = 0.8, decay = 2.0, stereo = true) {
    if (!audioCtx) return null;
    const rate = audioCtx.sampleRate;
    const length = Math.max(1, Math.floor(seconds * rate));
    const channels = stereo ? 2 : 1;
    const ir = audioCtx.createBuffer(channels, length, rate);
    for (let ch = 0; ch < channels; ch++) {
      const buf = ir.getChannelData(ch);
      for (let i = 0; i < length; i++) {
        const t = i / length;
        const env = Math.pow(1 - t, decay);
        buf[i] = (Math.random() * 2 - 1) * env;
      }
    }
    return ir;
  }

  function configureEffects(effects) {
    if (!audioCtx) return;
    try {
      staticEnabled = !!(effects && effects.static_noise);
      // Levels may be provided by the backend
      if (effects && typeof effects.static_noise_level !== 'undefined') {
        const v = parseFloat(effects.static_noise_level);
        staticNoiseLevel = isNaN(v) ? staticNoiseLevel : v;
      }
      if (effects && typeof effects.radio_noise_level !== 'undefined') {
        const v = parseFloat(effects.radio_noise_level);
        radioNoiseLevel = isNaN(v) ? radioNoiseLevel : v;
      }
      if (effects && typeof effects.wind_noise_level !== 'undefined') {
        const v = parseFloat(effects.wind_noise_level);
        windNoiseLevel = isNaN(v) ? windNoiseLevel : v;
      }
      const preset = (effects && effects.preset) ? String(effects.preset) : 'none';
      const useTannoy = !!(effects && effects.tannoy);
      const resolved = preset && preset !== 'none' ? preset : (useTannoy ? 'airport_pa' : 'none');
      configurePreset(resolved);
      currentPreset = resolved;
    } catch (e) {
      console.warn('configureEffects failed:', e);
    }
  }

  function configurePreset(name) {
    if (!audioCtx) return;
    try {
      // Reset baseline
      wetGain.gain.value = 0.0; dryGain.gain.value = 1.0;
      convolverGain.gain.value = 0.0; reverbLp.frequency.value = 20000;
      delayNode.delayTime.value = 0.14; feedbackGain.gain.value = 0.0; fbLpFilter.frequency.value = 20000; slapGain.gain.value = 0.0;
      multiTapGains.forEach(g => g.gain.value = 0.0);
      chorusDelay.delayTime.value = 0.012; chorusLfo.frequency.value = 0.25; chorusLfoGain.gain.value = 0.0; chorusGain.gain.value = 0.0;
      leftDelay.delayTime.value = 0.016; rightDelay.delayTime.value = 0.018; widenerGain.gain.value = 0.0;
      radioNoiseGain.gain.value = 0.0; windNoiseGain.gain.value = 0.0;
      // Neutral EQ, drive, compressor
      hpFilter.frequency.value = 80; lpFilter.frequency.value = 18000;
      driveShaper.curve = makeSoftClipCurve(1.0); driveShaper.oversample = '2x';
      compressor.threshold.value = -24; compressor.ratio.value = 2; compressor.attack.value = 0.01; compressor.release.value = 0.18; compressor.knee.value = 6;
      // Update per preset
      switch (name) {
        case 'airport_pa': {
          hpFilter.frequency.value = 280; lpFilter.frequency.value = 3200;
          driveShaper.curve = makeSoftClipCurve(1.4); driveShaper.oversample = '2x';
          convolver.buffer = makeImpulseResponse(0.8, 2.2, true);
          convolverGain.gain.value = 0.25;
          delayNode.delayTime.value = 0.16; feedbackGain.gain.value = 0.22; fbLpFilter.frequency.value = 4000; slapGain.gain.value = 0.20;
          compressor.threshold.value = -20; compressor.ratio.value = 3; compressor.attack.value = 0.006; compressor.release.value = 0.25; compressor.knee.value = 6;
          wetGain.gain.value = 0.35; dryGain.gain.value = 0.65;
          break;
        }
        case 'gate_desk': {
          hpFilter.frequency.value = 200; lpFilter.frequency.value = 4000;
          // Chorus: base 12–18 ms ±4 ms @ 0.25 Hz, mix ~10%
          chorusDelay.delayTime.value = 0.015; chorusLfo.frequency.value = 0.25; chorusLfoGain.gain.value = 0.004; chorusGain.gain.value = 0.10;
          // Early reflections multi-tap
          const taps = [0.008, 0.021, 0.034]; const gains = [0.25, 0.18, 0.12];
          for (let i = 0; i < taps.length; i++) { multiTapDelays[i].delayTime.value = taps[i]; multiTapGains[i].gain.value = gains[i]; }
          compressor.threshold.value = -20; compressor.ratio.value = 3; compressor.attack.value = 0.006; compressor.release.value = 0.25; compressor.knee.value = 6;
          wetGain.gain.value = 0.25; dryGain.gain.value = 0.75;
          break;
        }
        case 'atc_radio': {
          hpFilter.frequency.value = 330; lpFilter.frequency.value = 2600;
          driveShaper.curve = makeSoftClipCurve(2.2); driveShaper.oversample = '4x';
          compressor.threshold.value = -24; compressor.ratio.value = 4; compressor.attack.value = 0.003; compressor.release.value = 0.12; compressor.knee.value = 6;
          wetGain.gain.value = 0.5; dryGain.gain.value = 0.5;
          break;
        }
        case 'cabin_intercom': {
          hpFilter.frequency.value = 120; lpFilter.frequency.value = 6500;
          driveShaper.curve = makeSoftClipCurve(1.4); driveShaper.oversample = '2x';
          convolver.buffer = makeImpulseResponse(0.8, 2.0, true);
          convolverGain.gain.value = 0.18;
          compressor.threshold.value = -22; compressor.ratio.value = 2.5; compressor.attack.value = 0.01; compressor.release.value = 0.18; compressor.knee.value = 6;
          wetGain.gain.value = 0.20; dryGain.gain.value = 0.80;
          break;
        }
        case 'apron_outdoor': {
          hpFilter.frequency.value = 220; lpFilter.frequency.value = 3800;
          leftDelay.delayTime.value = 0.016; rightDelay.delayTime.value = 0.018; widenerGain.gain.value = 0.25;
          delayNode.delayTime.value = 0.29; feedbackGain.gain.value = 0.32; fbLpFilter.frequency.value = 2500; slapGain.gain.value = 0.22;
          convolver.buffer = makeImpulseResponse(1.3, 2.4, true);
          convolverGain.gain.value = 0.25;
          wetGain.gain.value = 0.30; dryGain.gain.value = 0.70;
          break;
        }
        case 'hangar_concourse': {
          hpFilter.frequency.value = 250; lpFilter.frequency.value = 3200;
          const taps = [0.007, 0.013, 0.023, 0.037]; const gains = [0.28, 0.22, 0.17, 0.12];
          for (let i = 0; i < taps.length; i++) { multiTapDelays[i].delayTime.value = taps[i]; multiTapGains[i].gain.value = gains[i]; }
          convolver.buffer = makeImpulseResponse(1.4, 2.2, true);
          convolverGain.gain.value = 0.24;
          compressor.threshold.value = -20; compressor.ratio.value = 3; compressor.attack.value = 0.006; compressor.release.value = 0.25; compressor.knee.value = 6;
          wetGain.gain.value = 0.26; dryGain.gain.value = 0.74;
          break;
        }
        case 'none':
        default: {
          // No processing: mostly dry
          wetGain.gain.value = 0.0; dryGain.gain.value = 1.0;
          break;
        }
      }
    } catch (e) {
      console.warn('configurePreset failed:', e);
    }
  }

  // Enhanced animation classes array for more diverse and smoother animations
  const animations = [
    'spin-in-smooth',
    'flip-in-smooth', 
    'bounce-in-dynamic',
    'slide-from-left',
    'slide-from-right',
    'slide-from-top',
    'slide-from-bottom',
    'zoom-spin-space',
    'elastic-distance',
    'spiral-edge',
    'twist-void'
  ];

  function levelForScore(score) {
    if (score <= 3) return 'bad';
    if (score <= 6) return 'ok';
    if (score <= 8) return 'good';
    return 'great';
  }

  function tierClass(level) { return 'tier-' + level; }

  function getRandomAnimation() {
    return animations[Math.floor(Math.random() * animations.length)];
  }

  function getCenterPosition() {
    // Since CSS now handles centering with fixed positioning,
    // we don't need to manually position the element
    return { x: 0, y: 0 };
  }

  let displayTimer = null;
  let previewActive = false;
  function showPreview(score = 1) {
    try {
      // Cancel any pending hide
      if (displayTimer) { clearTimeout(displayTimer); displayTimer = null; }
      // Reset classes and hide quote
      display.classList.remove('hidden', 'show');
      scoreFraction.classList.remove('tier-bad', 'tier-ok', 'tier-good', 'tier-great', ...animations);
      quoteDisplay.classList.remove('show');
      // Set a neutral tier class so colour comes from hue rotation only
      scoreFraction.classList.add('tier-good');
      voteScore.textContent = score;
      // Keep visible without auto-hide while preview is active
      void display.offsetWidth; // reflow
      display.classList.add('show');
    } catch (e) { /* noop */ }
  }
  function showAnimatedNumber(score, level, durationMs, quote = '', audioUrl = '', effects = null) {
    // Fixed banner display durations for predictable pacing
    const NO_AUDIO_HOLD_MS = 2000;  // Overlay hold when no audio is selected
    const AFTER_AUDIO_MS = 2000;     // Additional hold after audio finishes
    function hideOverlay() {
      display.classList.remove('show');
      display.classList.add('hidden');
      quoteDisplay.classList.remove('show');
    }
    // Clear previous timer
    if (displayTimer) {
      clearTimeout(displayTimer);
      displayTimer = null;
    }

    // Reset all classes - updated to include new animation classes
    display.classList.remove('hidden', 'show');
    scoreFraction.classList.remove(...animations, 'tier-bad', 'tier-ok', 'tier-good', 'tier-great');
    quoteDisplay.classList.remove('show');

    // Set the number
    voteScore.textContent = score;

    // Set the quote
    if (quote) {
      quoteDisplay.textContent = quote;
    }

    // Apply tier color to the score fraction container
    const tClass = tierClass(level);
    scoreFraction.classList.add(tClass);

    // Get center position and random animation
    const position = getCenterPosition();
    const randomAnim = getRandomAnimation();

    // Remove manual positioning since CSS handles centering
    display.style.left = '';
    display.style.top = '';
    display.style.transform = '';

    // Add random animation to score fraction
    scoreFraction.classList.add(randomAnim);

    // Show
    void display.offsetWidth; // Force reflow
    display.classList.add('show');

    // Show quote with delay
    if (quote) {
      setTimeout(() => {
        quoteDisplay.classList.add('show');
      }, 400); // Show quote faster after score animation
    }

    // Play audio only if available and TTS is enabled
    if (audioUrl && ttsEnabled) {
      initAudioGraph();
      configureEffects(effects);
      try { if (audioCtx && audioCtx.state !== 'running') { audioCtx.resume().catch(() => {}); } } catch (e) {}
      // Start muted to satisfy autoplay policies, then unmute shortly after
      try {
        quoteAudio.muted = true;
        quoteAudio.volume = 1.0;
      } catch (e) {}
      quoteAudio.src = audioUrl;
      // Ensure the media element reloads the new source before playing
      try { quoteAudio.load(); } catch (e) {}
      // Hide 2 seconds after audio finishes
      quoteAudio.onended = () => {
        if (!previewActive) {
          if (displayTimer) { clearTimeout(displayTimer); displayTimer = null; }
          displayTimer = setTimeout(() => { hideOverlay(); }, AFTER_AUDIO_MS);
        }
      };
      quoteAudio.play()
        .then(() => {
          // Attempt to unmute shortly after playback begins; if audioCtx is
          // still suspended, the element path should produce audible sound.
          try {
            setTimeout(() => {
              quoteAudio.muted = false;
            }, 150);
          } catch (e) { /* ignore */ }
        })
        .catch(e => {
        console.log('Audio playback failed:', e);
        if (audioCtx && audioCtx.state === 'suspended') {
          audioCtx.resume().catch(() => {});
        }
        // Autoplay may be blocked in regular browsers; OBS Browser Source is unaffected
        // Fallback to fixed banner duration if audio didn't play
        if (!previewActive) {
          if (displayTimer) { clearTimeout(displayTimer); displayTimer = null; }
          displayTimer = setTimeout(() => { hideOverlay(); }, NO_AUDIO_HOLD_MS);
        }
      });
    } else {
      // No audio: force-stop any previous playback and use fixed duration
      try {
        quoteAudio.pause();
        quoteAudio.currentTime = 0;
        quoteAudio.src = '';
      } catch (e) { /* ignore */ }
      // Keep old behavior (fixed duration)
      if (!previewActive) {
        if (displayTimer) { clearTimeout(displayTimer); displayTimer = null; }
        displayTimer = setTimeout(() => { hideOverlay(); }, NO_AUDIO_HOLD_MS);
      }
    }
  }

    function connectSSE() {
      const es = new EventSource('/stream');
      es.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data);
          if (payload.type === 'vote') {
          try {
            if (payload.hasOwnProperty('enable_tts')) {
              ttsEnabled = !!payload.enable_tts;
              if (!ttsEnabled) {
                // Belt-and-suspenders: stop any playing audio immediately
                try {
                  quoteAudio.pause();
                  quoteAudio.currentTime = 0;
                  quoteAudio.src = '';
                } catch (e) { /* ignore */ }
              }
            }
          } catch (e) { /* ignore */ }
          showAnimatedNumber(payload.score, payload.level, payload.duration_ms, payload.quote, payload.audio_url, payload.effects || null);
          } else if (payload.type === 'theme') {
            try {
              const deg = parseInt(payload.hue_deg || 0);
              document.documentElement.style.setProperty('--overlay-hue', `${isNaN(deg) ? 0 : deg}deg`);
            } catch (e) {
              // ignore theme update errors
            }
          } else if (payload.type === 'settings') {
            // Only handle audio effects; timing is fixed in JS now
            try {
              if (payload.hasOwnProperty('effects') && payload.effects) {
                configureEffects(payload.effects);
              }
            // Immediately stop any ongoing audio and suspend graph if TTS is disabled
              if (payload.hasOwnProperty('enable_tts')) {
                ttsEnabled = !!payload.enable_tts;
                if (!ttsEnabled) {
                  try {
                    quoteAudio.pause();
                    quoteAudio.currentTime = 0;
                    // Clear source so autoplay cannot re-trigger accidentally
                    quoteAudio.src = '';
                    quoteAudio.muted = true;
                  } catch (e) { /* ignore */ }
                  try {
                    if (audioCtx && audioCtx.state !== 'suspended') {
                      audioCtx.suspend().catch(() => {});
                    }
                  } catch (e) { /* ignore */ }
                  // Ensure noise beds are fully muted
                  try {
                    if (noiseGain) noiseGain.gain.value = 0.0;
                    if (radioNoiseGain) radioNoiseGain.gain.value = 0.0;
                    if (windNoiseGain) windNoiseGain.gain.value = 0.0;
                  } catch (e) { /* ignore */ }
                } else {
                  // Re-enable audio graph when TTS is turned back on
                  try {
                    if (audioCtx && audioCtx.state === 'suspended') {
                      audioCtx.resume().catch(() => {});
                    }
                    quoteAudio.muted = false;
                  } catch (e) { /* ignore */ }
                }
              }
            } catch (e) { /* ignore */ }
          } else if (payload.type === 'preview') {
            try {
              previewActive = !!payload.active;
              if (previewActive) {
                const scr = parseInt(payload.score || 1);
                showPreview(isNaN(scr) ? 1 : Math.max(1, Math.min(10, scr)));
              } else {
                // Turn off preview: hide immediately
              if (displayTimer) { clearTimeout(displayTimer); displayTimer = null; }
              display.classList.remove('show');
              display.classList.add('hidden');
              quoteDisplay.classList.remove('show');
            }
          } catch (e) { /* ignore */ }
        }
      } catch (e) {
        // ignore parse errors
      }
    };
    es.onerror = () => {
      // Let browser auto-reconnect; no manual handling needed
    };
  }

  // Init
  connectSSE();
  // Overlay has no on-screen settings; colour controlled via desktop UI
})();
