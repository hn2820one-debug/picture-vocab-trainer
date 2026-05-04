const STORAGE_KEYS = {
  prefs: "picture_vocab_prefs",
  history: "picture_vocab_attempt_history",
  stats: "picture_vocab_word_stats",
  mistakes: "picture_vocab_mistake_bank"
};

const TIMING = {
  hintMs: 3000,
  revealMs: 10000
};

const RESULT_LABELS = {
  correctBeforeReveal: "揭答前答對",
  correctAfterHint: "看提示後答對",
  correctAfterReveal: "看答案後答對",
  wrongBeforeReveal: "揭答前答錯",
  wrongAfterReveal: "看答案後仍答錯"
};

const FALLBACK_IMAGE = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 600">
  <rect width="900" height="600" fill="#efe3cf" />
  <rect x="80" y="80" width="740" height="440" rx="36" fill="#fff8ec" stroke="#1f2a2c" stroke-opacity="0.16" />
  <text x="450" y="255" text-anchor="middle" font-family="Trebuchet MS, Verdana, sans-serif" font-size="40" fill="#155e63">圖片載入失敗</text>
  <text x="450" y="318" text-anchor="middle" font-family="Trebuchet MS, Verdana, sans-serif" font-size="24" fill="#5f675f">請檢查圖片路徑，或補上對應圖片檔案。</text>
</svg>
`)}`;

const defaultPrefs = {
  shuffleQuestions: true,
  autoAdvanceMs: 1200
};

const state = {
  questionBank: [],
  queue: [],
  queueMode: "all",
  currentIndex: 0,
  currentQuestion: null,
  currentHintLevel: 0,
  answerRevealed: false,
  revealedManually: false,
  isAnswered: false,
  startTime: 0,
  sessionId: "",
  sessionAttempts: [],
  timers: {
    hint: null,
    reveal: null,
    clock: null,
    autoAdvance: null
  },
  prefs: loadStorage(STORAGE_KEYS.prefs, defaultPrefs),
  attemptHistory: loadStorage(STORAGE_KEYS.history, []),
  wordStats: loadStorage(STORAGE_KEYS.stats, {}),
  mistakeBank: loadStorage(STORAGE_KEYS.mistakes, [])
};

const dom = {};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  cacheDom();
  bindEvents();
  ensureStorageDefaults();
  renderSettings();
  updateHomeSnapshot();
  await loadQuestionBank();
  showView("home");
}

function cacheDom() {
  dom.views = document.querySelectorAll(".view");
  dom.navHome = document.getElementById("nav-home");
  dom.datasetStatus = document.getElementById("dataset-status");
  dom.homeSnapshot = document.getElementById("home-snapshot");
  dom.startPractice = document.getElementById("start-practice");
  dom.reviewMistakes = document.getElementById("review-mistakes");
  dom.openProgress = document.getElementById("open-progress");
  dom.openSettings = document.getElementById("open-settings");
  dom.practiceModeLabel = document.getElementById("practice-mode-label");
  dom.questionCounter = document.getElementById("question-counter");
  dom.timerBadge = document.getElementById("timer-badge");
  dom.exitPractice = document.getElementById("exit-practice");
  dom.questionImage = document.getElementById("question-image");
  dom.imageFallback = document.getElementById("image-fallback");
  dom.questionCategory = document.getElementById("question-category");
  dom.questionLevel = document.getElementById("question-level");
  dom.questionPos = document.getElementById("question-pos");
  dom.hintStatus = document.getElementById("hint-status");
  dom.hintText = document.getElementById("hint-text");
  dom.answerText = document.getElementById("answer-text");
  dom.choiceGrid = document.getElementById("choice-grid");
  dom.feedbackPanel = document.getElementById("feedback-panel");
  dom.feedbackTitle = document.getElementById("feedback-title");
  dom.feedbackCopy = document.getElementById("feedback-copy");
  dom.nextQuestion = document.getElementById("next-question");
  dom.revealAnswer = document.getElementById("reveal-answer");
  dom.restartQueue = document.getElementById("restart-queue");
  dom.summarySnapshot = document.getElementById("summary-snapshot");
  dom.summaryBreakdown = document.getElementById("summary-breakdown");
  dom.summaryHome = document.getElementById("summary-home");
  dom.summaryRestart = document.getElementById("summary-restart");
  dom.summaryReview = document.getElementById("summary-review");
  dom.progressSnapshot = document.getElementById("progress-snapshot");
  dom.exportLogJson = document.getElementById("export-log-json");
  dom.exportLogCsv = document.getElementById("export-log-csv");
  dom.weakWords = document.getElementById("weak-words");
  dom.categoryPerformance = document.getElementById("category-performance");
  dom.recentAttempts = document.getElementById("recent-attempts");
  dom.progressHome = document.getElementById("progress-home");
  dom.settingsHome = document.getElementById("settings-home");
  dom.settingsForm = document.getElementById("settings-form");
  dom.shuffleQuestions = document.getElementById("shuffle-questions");
  dom.autoAdvanceMs = document.getElementById("auto-advance-ms");
  dom.resetStorage = document.getElementById("reset-storage");
}

function bindEvents() {
  dom.navHome.addEventListener("click", goHome);
  dom.startPractice.addEventListener("click", () => startSession("all"));
  dom.reviewMistakes.addEventListener("click", () => startSession("mistakes"));
  dom.openProgress.addEventListener("click", () => {
    renderProgress();
    showView("progress");
  });
  dom.openSettings.addEventListener("click", () => showView("settings"));
  dom.exitPractice.addEventListener("click", goHome);
  dom.nextQuestion.addEventListener("click", advanceQuestion);
  dom.revealAnswer.addEventListener("click", () => revealCurrentAnswer(true));
  dom.restartQueue.addEventListener("click", () => startSession(state.queueMode));
  dom.summaryHome.addEventListener("click", goHome);
  dom.summaryRestart.addEventListener("click", () => startSession("all"));
  dom.summaryReview.addEventListener("click", () => startSession("mistakes"));
  dom.exportLogJson.addEventListener("click", () => exportAttemptHistory("json"));
  dom.exportLogCsv.addEventListener("click", () => exportAttemptHistory("csv"));
  dom.progressHome.addEventListener("click", goHome);
  dom.settingsHome.addEventListener("click", goHome);
  dom.settingsForm.addEventListener("submit", saveSettings);
  dom.resetStorage.addEventListener("click", resetLocalData);
}

async function loadQuestionBank() {
  try {
    const response = await fetch("data/image_words.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    state.questionBank = Array.isArray(data) ? data : [];
    setHomeMessage(`已載入 ${state.questionBank.length} 題。`);
  } catch (error) {
    state.questionBank = [];
    setHomeMessage("讀取 data/image_words.json 失敗，請改用靜態伺服器開啟頁面。");
    console.error("Failed to load question bank", error);
  }

  syncHomeButtons();
  updateHomeSnapshot();
}

function showView(viewName) {
  clearTimers();
  dom.views.forEach((view) => {
    view.classList.toggle("is-active", view.id === `view-${viewName}`);
  });
}

function startSession(mode) {
  if (!state.questionBank.length) {
    setHomeMessage("題庫目前是空的，請先準備 data/image_words.json。");
    showView("home");
    return;
  }

  let queue = [];
  if (mode === "mistakes") {
    const mistakeIds = new Set(state.mistakeBank);
    queue = state.questionBank.filter((question) => mistakeIds.has(question.id));
    if (!queue.length) {
      setHomeMessage("目前沒有可重練的錯題。");
      showView("home");
      syncHomeButtons();
      return;
    }
  } else {
    queue = [...state.questionBank];
  }

  state.queueMode = mode;
  state.currentIndex = 0;
  state.sessionId = generateSessionId();
  state.sessionAttempts = [];
  state.queue = state.prefs.shuffleQuestions ? shuffle(queue) : queue;
  dom.practiceModeLabel.textContent = mode === "mistakes" ? "錯題重練" : "完整練習";
  showView("practice");
  renderCurrentQuestion();
}

function renderCurrentQuestion() {
  clearTimers();

  if (state.currentIndex >= state.queue.length) {
    renderSummary();
    showView("summary");
    return;
  }

  const question = state.queue[state.currentIndex];
  state.currentQuestion = question;
  state.currentHintLevel = 0;
  state.answerRevealed = false;
  state.revealedManually = false;
  state.isAnswered = false;
  state.startTime = performance.now();

  dom.questionCounter.textContent = `${state.currentIndex + 1} / ${state.queue.length}`;
  dom.timerBadge.textContent = "0.0s";
  dom.questionCategory.textContent = question.category;
  dom.questionLevel.textContent = String(question.level);
  dom.questionPos.textContent = question.partOfSpeech;
  dom.hintStatus.textContent = "尚未顯示提示。3 秒後顯示提示，10 秒後顯示答案。";
  dom.hintText.textContent = "";
  dom.answerText.textContent = "";
  dom.feedbackPanel.dataset.tone = "warning";
  dom.feedbackTitle.textContent = "請先選擇一個答案。";
  dom.feedbackCopy.textContent = "你的作答結果、用時、提示等級與揭答狀態會顯示在這裡。";
  dom.nextQuestion.disabled = true;
  dom.revealAnswer.disabled = false;
  dom.imageFallback.classList.add("hidden");

  dom.questionImage.onerror = () => {
    dom.imageFallback.classList.remove("hidden");
    dom.questionImage.onerror = null;
    dom.questionImage.src = FALLBACK_IMAGE;
  };
  dom.questionImage.src = question.image;
  dom.questionImage.alt = `題目圖片：${question.answer}`;

  renderChoices();
  startTimers();
}

function renderChoices(selectedChoice) {
  const question = state.currentQuestion;
  dom.choiceGrid.innerHTML = "";

  question.choices.forEach((choice, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "choice-button";
    button.textContent = `${String.fromCharCode(65 + index)}. ${choice}`;
    button.disabled = state.isAnswered;

    if (state.answerRevealed && choice === question.answer) {
      button.classList.add("is-answer");
    }

    if (state.isAnswered && selectedChoice === choice) {
      button.classList.add(choice === question.answer ? "is-correct" : "is-wrong");
    }

    if (state.isAnswered && selectedChoice !== choice && choice === question.answer) {
      button.classList.add("is-answer");
    }

    button.addEventListener("click", () => handleChoice(choice));
    dom.choiceGrid.appendChild(button);
  });
}

function startTimers() {
  state.timers.clock = window.setInterval(() => {
    const seconds = (performance.now() - state.startTime) / 1000;
    dom.timerBadge.textContent = `${seconds.toFixed(1)}s`;
  }, 100);

  state.timers.hint = window.setTimeout(() => {
    if (state.isAnswered || !state.currentQuestion || state.answerRevealed) {
      return;
    }

    state.currentHintLevel = 1;
    dom.hintStatus.textContent = "第一層提示已顯示。";
    dom.hintText.textContent = state.currentQuestion.hint1 || "目前沒有第一層提示。";
  }, TIMING.hintMs);

  state.timers.reveal = window.setTimeout(() => {
    if (state.isAnswered || !state.currentQuestion || state.answerRevealed) {
      return;
    }

    revealCurrentAnswer(false);
  }, TIMING.revealMs);
}

function revealCurrentAnswer(manual) {
  if (!state.currentQuestion || state.isAnswered || state.answerRevealed) {
    return;
  }

  clearRevealTimers();
  state.currentHintLevel = 2;
  state.answerRevealed = true;
  state.revealedManually = manual;
  dom.hintStatus.textContent = manual
    ? "你已提前顯示答案。之後作答會記為看答案後作答。"
    : "已顯示答案。這不算真正掌握。";
  dom.hintText.textContent = state.currentQuestion.hint2 || state.currentQuestion.hint1 || "目前沒有額外提示。";
  dom.answerText.textContent = `答案：${state.currentQuestion.answer}`;
  dom.revealAnswer.disabled = true;
  renderChoices();
}

function handleChoice(choice) {
  if (state.isAnswered || !state.currentQuestion) {
    return;
  }

  state.isAnswered = true;
  clearTimers();
  dom.revealAnswer.disabled = true;

  const responseTimeMs = Math.round(performance.now() - state.startTime);
  const isCorrect = choice === state.currentQuestion.answer;
  const resultType = classifyAttempt(isCorrect);
  const attempt = {
    sessionId: state.sessionId,
    questionId: state.currentQuestion.id,
    image: state.currentQuestion.image,
    questionZh: state.currentQuestion.zh || "",
    correctAnswer: state.currentQuestion.answer,
    userAnswer: choice,
    isCorrect,
    responseTimeMs,
    hintLevel: state.currentHintLevel,
    answerRevealed: state.answerRevealed,
    revealedManually: state.revealedManually,
    resultType,
    isConfidentError: !isCorrect && !state.answerRevealed,
    category: state.currentQuestion.category,
    level: state.currentQuestion.level,
    timestamp: Date.now()
  };

  state.sessionAttempts.push(attempt);
  state.attemptHistory.push(attempt);
  updateWordStats(attempt);
  updateMistakeBank(attempt);
  persistState();
  syncHomeButtons();
  updateHomeSnapshot();

  dom.answerText.textContent = `答案：${state.currentQuestion.answer}`;
  if (!dom.hintText.textContent) {
    dom.hintText.textContent = state.currentQuestion.hint2 || state.currentQuestion.hint1 || "";
  }
  renderChoices(choice);
  renderFeedback(attempt);
  dom.nextQuestion.disabled = false;

  if (state.prefs.autoAdvanceMs > 0) {
    state.timers.autoAdvance = window.setTimeout(() => {
      advanceQuestion();
    }, state.prefs.autoAdvanceMs);
  }
}

function advanceQuestion() {
  if (!state.currentQuestion) {
    return;
  }

  clearTimers();
  state.currentIndex += 1;
  renderCurrentQuestion();
}

function renderFeedback(attempt) {
  const tone = attempt.isCorrect ? (attempt.answerRevealed ? "warning" : "success") : "danger";
  dom.feedbackPanel.dataset.tone = tone;
  dom.feedbackTitle.textContent = RESULT_LABELS[attempt.resultType];
  dom.feedbackCopy.textContent = `作答時間 ${formatMs(attempt.responseTimeMs)} | 提示等級 ${attempt.hintLevel} | 已揭答 ${attempt.answerRevealed ? "是" : "否"} | 手動揭答 ${attempt.revealedManually ? "是" : "否"}`;
}

function renderSummary() {
  const counts = summarizeResults(state.sessionAttempts);
  const averageTime = average(state.sessionAttempts.map((attempt) => attempt.responseTimeMs));
  const masteredCount = counts.correctBeforeReveal + counts.correctAfterHint;

  dom.summarySnapshot.innerHTML = "";
  dom.summaryBreakdown.innerHTML = "";

  [
    { label: "題目數", value: String(state.sessionAttempts.length) },
    { label: "真正掌握", value: String(masteredCount) },
    { label: "錯題庫", value: String(state.mistakeBank.length) },
    { label: "平均作答時間", value: formatMs(averageTime) }
  ].forEach((item) => {
    dom.summarySnapshot.appendChild(createSnapshotCard(item.label, item.value));
  });

  Object.entries(RESULT_LABELS).forEach(([resultType, label]) => {
    const row = document.createElement("div");
    row.className = "summary-item";
    row.innerHTML = `<span>${label}</span><strong>${counts[resultType] || 0}</strong>`;
    dom.summaryBreakdown.appendChild(row);
  });
}

function renderProgress() {
  const counts = summarizeResults(state.attemptHistory);
  const averageTime = average(state.attemptHistory.map((attempt) => attempt.responseTimeMs));
  const masteredRate = state.attemptHistory.length
    ? Math.round(((counts.correctBeforeReveal + counts.correctAfterHint) / state.attemptHistory.length) * 100)
    : 0;

  dom.progressSnapshot.innerHTML = "";
  [
    { label: "累計作答次數", value: String(state.attemptHistory.length) },
    { label: "掌握率", value: `${masteredRate}%` },
    { label: "平均作答時間", value: formatMs(averageTime) },
    { label: "目前錯題數", value: String(state.mistakeBank.length) }
  ].forEach((item) => {
    dom.progressSnapshot.appendChild(createSnapshotCard(item.label, item.value));
  });

  renderWeakWords();
  renderCategoryPerformance();
  renderRecentAttempts();
}

function renderWeakWords() {
  const entries = Object.entries(state.wordStats)
    .map(([questionId, stats]) => ({ questionId, ...stats }))
    .sort((left, right) => (right.wrongBeforeReveal + right.wrongAfterReveal) - (left.wrongBeforeReveal + left.wrongAfterReveal))
    .slice(0, 5);

  if (!entries.length) {
    dom.weakWords.innerHTML = '<p class="table-note">目前還沒有作答紀錄。</p>';
    return;
  }

  const container = document.createElement("div");
  container.className = "weak-word-list";

  entries.forEach((entry) => {
    const question = findQuestion(entry.questionId);
    const row = document.createElement("div");
    row.className = "weak-word-item";
    row.innerHTML = `
      <div>
        <strong>${question ? question.answer : entry.questionId}</strong>
        <div class="weak-word-meta">${question ? question.category : "未知分類"}</div>
      </div>
      <div class="weak-word-meta">錯誤 ${entry.wrongBeforeReveal + entry.wrongAfterReveal} 次 / 作答 ${entry.attempts} 次</div>
    `;
    container.appendChild(row);
  });

  dom.weakWords.innerHTML = "";
  dom.weakWords.appendChild(container);
}

function renderCategoryPerformance() {
  const categoryMap = new Map();

  state.attemptHistory.forEach((attempt) => {
    const current = categoryMap.get(attempt.category) || { attempts: 0, mastered: 0 };
    current.attempts += 1;
    if (attempt.resultType === "correctBeforeReveal" || attempt.resultType === "correctAfterHint") {
      current.mastered += 1;
    }
    categoryMap.set(attempt.category, current);
  });

  if (!categoryMap.size) {
    dom.categoryPerformance.innerHTML = '<p class="table-note">目前還沒有分類統計。</p>';
    return;
  }

  const table = document.createElement("div");
  table.className = "category-table";

  Array.from(categoryMap.entries())
    .sort((left, right) => left[0].localeCompare(right[0]))
    .forEach(([category, metrics]) => {
      const accuracy = Math.round((metrics.mastered / metrics.attempts) * 100);
      const row = document.createElement("div");
      row.className = "category-row";
      row.innerHTML = `
        <div>
          <strong>${category}</strong>
          <div class="table-note">掌握 ${metrics.mastered} 題 / 作答 ${metrics.attempts} 次</div>
        </div>
        <strong>${accuracy}%</strong>
      `;
      table.appendChild(row);
    });

  dom.categoryPerformance.innerHTML = "";
  dom.categoryPerformance.appendChild(table);
}

function renderRecentAttempts() {
  const recent = [...state.attemptHistory].slice(-10).reverse();
  if (!recent.length) {
    dom.recentAttempts.innerHTML = '<p class="table-note">目前還沒有可匯出的作答紀錄。</p>';
    return;
  }

  const list = document.createElement("div");
  list.className = "weak-word-list";

  recent.forEach((attempt) => {
    const row = document.createElement("div");
    row.className = "summary-item";
    row.innerHTML = `
      <div>
        <strong>${attempt.correctAnswer}</strong>
        <div class="table-note">${RESULT_LABELS[attempt.resultType]} | ${formatLocalTime(attempt.timestamp)}</div>
      </div>
      <div class="table-note">作答：${attempt.userAnswer} | ${formatMs(attempt.responseTimeMs)}</div>
    `;
    list.appendChild(row);
  });

  dom.recentAttempts.innerHTML = "";
  dom.recentAttempts.appendChild(list);
}

function exportAttemptHistory(format) {
  if (!state.attemptHistory.length) {
    window.alert("目前沒有可匯出的答題紀錄。");
    return;
  }

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  if (format === "json") {
    const payload = {
      exportedAt: new Date().toISOString(),
      totalAttempts: state.attemptHistory.length,
      hintRuleMs: TIMING,
      attempts: state.attemptHistory
    };
    downloadFile(`picture_vocab_log_${stamp}.json`, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
    return;
  }

  const headers = [
    "sessionId",
    "timestamp",
    "questionId",
    "questionZh",
    "category",
    "level",
    "correctAnswer",
    "userAnswer",
    "isCorrect",
    "resultType",
    "responseTimeMs",
    "hintLevel",
    "answerRevealed",
    "revealedManually",
    "isConfidentError",
    "image"
  ];
  const rows = state.attemptHistory.map((attempt) => headers.map((header) => csvEscape(attempt[header] ?? "")).join(","));
  const csv = [headers.join(","), ...rows].join("\n");
  downloadFile(`picture_vocab_log_${stamp}.csv`, csv, "text/csv;charset=utf-8");
}

function saveSettings(event) {
  event.preventDefault();
  state.prefs = {
    shuffleQuestions: dom.shuffleQuestions.checked,
    autoAdvanceMs: Number(dom.autoAdvanceMs.value)
  };
  writeStorage(STORAGE_KEYS.prefs, state.prefs);
  setHomeMessage("設定已儲存。");
  updateHomeSnapshot();
  showView("home");
}

function resetLocalData() {
  const shouldReset = window.confirm("要清空本機的作答紀錄、統計資料與錯題庫嗎？");
  if (!shouldReset) {
    return;
  }

  state.attemptHistory = [];
  state.wordStats = {};
  state.mistakeBank = [];
  persistState();
  syncHomeButtons();
  updateHomeSnapshot();
  setHomeMessage("本機資料已重設。");
  showView("home");
}

function renderSettings() {
  dom.shuffleQuestions.checked = Boolean(state.prefs.shuffleQuestions);
  dom.autoAdvanceMs.value = String(state.prefs.autoAdvanceMs);
}

function ensureStorageDefaults() {
  writeStorage(STORAGE_KEYS.prefs, state.prefs);
  writeStorage(STORAGE_KEYS.history, state.attemptHistory);
  writeStorage(STORAGE_KEYS.stats, state.wordStats);
  writeStorage(STORAGE_KEYS.mistakes, state.mistakeBank);
}

function goHome() {
  clearTimers();
  updateHomeSnapshot();
  showView("home");
}

function clearRevealTimers() {
  if (state.timers.hint) {
    window.clearTimeout(state.timers.hint);
    state.timers.hint = null;
  }
  if (state.timers.reveal) {
    window.clearTimeout(state.timers.reveal);
    state.timers.reveal = null;
  }
}

function clearTimers() {
  Object.values(state.timers).forEach((timer) => {
    if (timer) {
      window.clearTimeout(timer);
      window.clearInterval(timer);
    }
  });

  state.timers = {
    hint: null,
    reveal: null,
    clock: null,
    autoAdvance: null
  };
}

function classifyAttempt(isCorrect) {
  if (state.answerRevealed) {
    return isCorrect ? "correctAfterReveal" : "wrongAfterReveal";
  }

  if (isCorrect && state.currentHintLevel === 0) {
    return "correctBeforeReveal";
  }

  if (isCorrect) {
    return "correctAfterHint";
  }

  return "wrongBeforeReveal";
}

function updateWordStats(attempt) {
  const existing = state.wordStats[attempt.questionId] || {
    attempts: 0,
    correctBeforeReveal: 0,
    correctAfterHint: 0,
    correctAfterReveal: 0,
    wrongBeforeReveal: 0,
    wrongAfterReveal: 0,
    lastResponseTimeMs: 0,
    lastTimestamp: 0
  };

  existing.attempts += 1;
  existing[attempt.resultType] += 1;
  existing.lastResponseTimeMs = attempt.responseTimeMs;
  existing.lastTimestamp = attempt.timestamp;
  state.wordStats[attempt.questionId] = existing;
}

function updateMistakeBank(attempt) {
  const mastered = attempt.resultType === "correctBeforeReveal" || attempt.resultType === "correctAfterHint";
  const mistakeIds = new Set(state.mistakeBank);

  if (mastered) {
    mistakeIds.delete(attempt.questionId);
  } else {
    mistakeIds.add(attempt.questionId);
  }

  state.mistakeBank = Array.from(mistakeIds);
}

function persistState() {
  writeStorage(STORAGE_KEYS.history, state.attemptHistory.slice(-2000));
  writeStorage(STORAGE_KEYS.stats, state.wordStats);
  writeStorage(STORAGE_KEYS.mistakes, state.mistakeBank);
}

function syncHomeButtons() {
  const hasData = state.questionBank.length > 0;
  dom.startPractice.disabled = !hasData;
  dom.openProgress.disabled = !hasData;
  dom.openSettings.disabled = false;
  dom.reviewMistakes.disabled = !hasData || state.mistakeBank.length === 0;
}

function updateHomeSnapshot() {
  const counts = summarizeResults(state.attemptHistory);
  const accuracy = state.attemptHistory.length
    ? Math.round(((counts.correctBeforeReveal + counts.correctAfterHint) / state.attemptHistory.length) * 100)
    : 0;

  dom.homeSnapshot.innerHTML = "";
  [
    { label: "題庫總數", value: String(state.questionBank.length) },
    { label: "作答紀錄", value: String(state.attemptHistory.length) },
    { label: "錯題庫", value: String(state.mistakeBank.length) },
    { label: "掌握率", value: `${accuracy}%` }
  ].forEach((item) => {
    dom.homeSnapshot.appendChild(createSnapshotCard(item.label, item.value));
  });
}

function createSnapshotCard(label, value) {
  const card = document.createElement("div");
  card.className = "snapshot-card";
  card.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
  return card;
}

function summarizeResults(attempts) {
  return attempts.reduce((summary, attempt) => {
    summary[attempt.resultType] += 1;
    return summary;
  }, {
    correctBeforeReveal: 0,
    correctAfterHint: 0,
    correctAfterReveal: 0,
    wrongBeforeReveal: 0,
    wrongAfterReveal: 0
  });
}

function average(values) {
  if (!values.length) {
    return 0;
  }

  const total = values.reduce((sum, value) => sum + value, 0);
  return Math.round(total / values.length);
}

function formatMs(value) {
  return `${(value / 1000).toFixed(1)} 秒`;
}

function formatLocalTime(timestamp) {
  return new Date(timestamp).toLocaleString("zh-TW", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function shuffle(items) {
  const copy = [...items];

  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[swapIndex]] = [copy[swapIndex], copy[index]];
  }

  return copy;
}

function setHomeMessage(message) {
  dom.datasetStatus.textContent = message;
}

function findQuestion(questionId) {
  return state.questionBank.find((item) => item.id === questionId) || null;
}

function generateSessionId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `session-${Date.now()}`;
}

function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function csvEscape(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function loadStorage(key, fallbackValue) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallbackValue;
  } catch (error) {
    console.warn(`Could not read storage key ${key}`, error);
    return fallbackValue;
  }
}

function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    console.warn(`Could not write storage key ${key}`, error);
  }
}