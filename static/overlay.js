/* Animated number overlay for 1080x1920 OBS with random animations */
(function () {
  const $ = (id) => document.getElementById(id);

  const display = $('number-display');
  const voteScore = $('vote-score');
  const scoreFraction = display.querySelector('.score-fraction');
  const quoteDisplay = $('quote-display');
  const quoteAudio = $('quote-audio');

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
  function showAnimatedNumber(score, level, durationMs, quote = '', audioUrl = '') {
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

    // Play audio if available
    if (audioUrl) {
      quoteAudio.src = audioUrl;
      quoteAudio.play().catch(e => {
        console.log('Audio playback failed:', e);
      });
    }

    const ms = typeof durationMs === 'number' ? durationMs : (window.BANNER_DURATION_MS || 4000);
    displayTimer = setTimeout(() => {
      display.classList.remove('show');
      display.classList.add('hidden');
      quoteDisplay.classList.remove('show');
    }, ms);
  }

  function connectSSE() {
    const es = new EventSource('/stream');
    es.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data);
        if (payload.type === 'vote') {
          showAnimatedNumber(payload.score, payload.level, payload.duration_ms, payload.quote, payload.audio_url);
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
})();
