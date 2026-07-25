// ─── Copy to Clipboard ───
function copyInstall() {
  const text = 'pip install siggy-memory';
  const el = document.getElementById('install-copy');
  const pill = document.getElementById('install-pill');

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      el.textContent = 'copied';
      el.classList.add('copied');
      pill.style.pointerEvents = 'none';
      setTimeout(() => {
        el.textContent = 'copy';
        el.classList.remove('copied');
        pill.style.pointerEvents = '';
      }, 2000);
    }).catch(fallbackCopy);
  } else {
    fallbackCopy();
  }

  function fallbackCopy() {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      el.textContent = 'copied';
      el.classList.add('copied');
      pill.style.pointerEvents = 'none';
      setTimeout(() => {
        el.textContent = 'copy';
        el.classList.remove('copied');
        pill.style.pointerEvents = '';
      }, 2000);
    } catch {
      el.textContent = 'copy failed';
      setTimeout(() => { el.textContent = 'copy'; }, 1500);
    }
    document.body.removeChild(ta);
  }
}

// ─── Terminal Typing Animation ───
const terminalSequences = [
  {
    prompt: '$ siggy up python app.py',
    output: [
      '<span class="output">Siggy Up</span>',
      '<span class="success">  [OK]</span> <span class="output">Qdrant ready</span>',
      '<span class="success">  [OK]</span> <span class="output">SigNoz ready</span>',
      '<span class="success">  [OK]</span> <span class="output">MCP server ready</span>',
      '<span class="success">  [OK]</span> <span class="output">Backend ready</span>',
      '',
      '<span class="output">  Service   </span><span class="highlight">demo-api</span>',
      '<span class="output">  Framework </span><span class="highlight">flask</span>',
      '<span class="output">  Session   </span><span class="highlight">sess_a1b2c3d4</span>',
      '',
      '<span class="success">  Application started (OTel → localhost:4317)</span>',
      '<span class="output">  How it works:</span>',
      '<span class="output">    1. Your app sends traces to SigNoz</span>',
      '<span class="output">    2. SigNoz detects errors in traces</span>',
      '<span class="output">    3. Siggy enriches with memory</span>',
      '<span class="output">    4. Recommendations appear in SigNoz</span>',
    ],
  },
  {
    prompt: '$ siggy investigate "Redis timeout in checkout"',
    output: [
      '<span class="output">Investigating: Redis timeout in checkout</span>',
      '<span class="output">-------------------------------------------</span>',
      '',
      '<span class="output">  Root cause: </span><span class="highlight">Redis connection pool exhausted</span>',
      '<span class="output">  Confidence: </span><span class="success">87%</span>',
      '<span class="output">  Similar incidents: </span><span class="highlight">3 found</span>',
      '',
      '<span class="output">  Recommendation:</span>',
      '<span class="success">  Increase Redis pool size from 64 to 128.</span>',
      '<span class="success">  Set idle connection timeout to 30s.</span>',
    ],
  },
  {
    prompt: '$ siggy demo',
    output: [
      '<span class="output">Siggy Demo</span>',
      '<span class="success">========================================</span>',
      '',
      '<span class="success">  [OK]</span> <span class="output">Backend ready</span>',
      '<span class="success">  [OK]</span> <span class="output">Seeded 4 demo incidents</span>',
      '<span class="success">  [OK]</span> <span class="output">Seeded 3 experience records</span>',
      '<span class="success">  [OK]</span> <span class="output">Graph synced</span>',
      '',
      '<span class="output">  API Health:</span>',
      '<span class="highlight">  http://localhost:8010/api/v1/health</span>',
    ],
  },
];

let currentSeq = 0;
let typingInterval = null;
let isTyping = false;

function typeTerminal() {
  const el = document.getElementById('terminal-code');
  if (!el) return;

  const seq = terminalSequences[currentSeq];
  el.innerHTML = '';

  let charIdx = 0;
  let inTag = false;
  let tagBuffer = '';

  isTyping = true;

  typingInterval = setInterval(() => {
    if (charIdx < seq.prompt.length) {
      const ch = seq.prompt[charIdx];
      if (ch === '<') {
        inTag = true;
        tagBuffer = '<';
      } else if (inTag) {
        tagBuffer += ch;
        if (ch === '>') {
          inTag = false;
          el.innerHTML += tagBuffer;
          tagBuffer = '';
        }
      } else {
        el.innerHTML += ch;
      }
      charIdx++;
    } else {
      clearInterval(typingInterval);
      let outputIdx = 0;
      const outputInterval = setInterval(() => {
        if (outputIdx < seq.output.length) {
          el.innerHTML += '\n' + seq.output[outputIdx];
          el.scrollTop = el.scrollHeight;
          outputIdx++;
        } else {
          clearInterval(outputInterval);
          isTyping = false;
          setTimeout(() => {
            currentSeq = (currentSeq + 1) % terminalSequences.length;
            typeTerminal();
          }, 4000);
        }
      }, 80);
    }
  }, 40);
}

let terminalStarted = false;

// ─── Scroll Fade-In ───
function initFadeIn() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });

  document.querySelectorAll('.fade-in').forEach((el) => {
    observer.observe(el);
  });
}

// ─── Nav Active State ───
function initNavHighlight() {
  const sections = ['problem', 'features', 'how-it-works', 'architecture', 'cli', 'numbers', 'install'];
  const navPills = document.querySelectorAll('.nav-pill[data-section]');

  sections.forEach((id) => {
    const link = document.querySelector(`.nav-pill[href="#${id}"]`);
    if (link) link.setAttribute('data-section', id);
  });

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const id = entry.target.getAttribute('id');
        document.querySelectorAll('.nav-pill').forEach((p) => p.classList.remove('active'));
        const active = document.querySelector(`.nav-pill[href="#${id}"]`);
        if (active) active.classList.add('active');
      }
    });
  }, { threshold: 0.3, rootMargin: '-64px 0px -40% 0px' });

  sections.forEach((id) => {
    const el = document.getElementById(id);
    if (el) observer.observe(el);
  });
}

// ─── Terminal Observer ───
function initTerminalObserver() {
  const terminal = document.querySelector('.terminal');
  if (!terminal) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting && !terminalStarted) {
        terminalStarted = true;
        typeTerminal();
      }
    });
  }, { threshold: 0.3 });

  observer.observe(terminal);
}

// ─── Nav Shadow on Scroll ───
function initNavShadow() {
  const nav = document.getElementById('nav');
  window.addEventListener('scroll', () => {
    if (window.scrollY > 10) {
      nav.style.boxShadow = '0 1px 6px rgba(0,0,0,0.08)';
    } else {
      nav.style.boxShadow = 'none';
    }
  }, { passive: true });
}

// ─── Init ───
document.addEventListener('DOMContentLoaded', () => {
  initFadeIn();
  initNavHighlight();
  initTerminalObserver();
  initNavShadow();
});
