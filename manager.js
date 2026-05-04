const MANAGER_STORAGE_KEY = "picture_vocab_manager_state_v1";
const UPLOAD_STORAGE_KEY = "picture_vocab_uploads_v1";
const MANIFEST_PATH = "data/manager_candidates.json";
const MAX_DISPLAY_OPTIONS = 4;

const managerState = {
  manifest: null,
  entries: [],
  currentIndex: 0,
  selections: loadManagerState(),
  uploadedImages: loadUploadedImages()
};

const managerDom = {};

document.addEventListener("DOMContentLoaded", initManager);

async function initManager() {
  cacheManagerDom();
  bindManagerEvents();
  await loadManifest();
}

function cacheManagerDom() {
  managerDom.managerCounter = document.getElementById("manager-counter");
  managerDom.selectionCounter = document.getElementById("selection-counter");
  managerDom.managerCategory = document.getElementById("manager-category");
  managerDom.managerWord = document.getElementById("manager-word");
  managerDom.managerQuery = document.getElementById("manager-query");
  managerDom.managerZhInput = document.getElementById("manager-zh-input");
  managerDom.currentApprovedImage = document.getElementById("current-approved-image");
  managerDom.currentApprovedMeta = document.getElementById("current-approved-meta");
  managerDom.prevEntry = document.getElementById("prev-entry");
  managerDom.nextEntry = document.getElementById("next-entry");
  managerDom.exportSelections = document.getElementById("export-selections");
  managerDom.resetManager = document.getElementById("reset-manager");
  managerDom.candidateGrid = document.getElementById("candidate-grid");
  managerDom.uploadInput = document.getElementById("upload-image-input");
  managerDom.selectionSummary = document.getElementById("selection-summary");
}

function bindManagerEvents() {
  managerDom.prevEntry.addEventListener("click", () => moveEntry(-1));
  managerDom.nextEntry.addEventListener("click", () => moveEntry(1));
  managerDom.exportSelections.addEventListener("click", exportSelections);
  managerDom.resetManager.addEventListener("click", resetSelections);
  managerDom.managerZhInput.addEventListener("input", handleZhInput);
  managerDom.uploadInput.addEventListener("change", handleFileSelected);
}

async function loadManifest() {
  try {
    const response = await fetch(MANIFEST_PATH, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    managerState.manifest = payload;
    managerState.entries = Array.isArray(payload.entries) ? payload.entries : [];
    renderManager();
  } catch (error) {
    managerDom.managerCategory.textContent = "載入失敗";
    managerDom.managerWord.textContent = "找不到 data/manager_candidates.json";
    managerDom.managerQuery.textContent = "請先執行 python tools/question_bank_manager.py manifest。";
    managerDom.candidateGrid.innerHTML = '<div class="candidate-card is-empty"><p>請先建立管理頁 manifest，之後再重新整理頁面。</p></div>';
    console.error("Failed to load manager manifest", error);
  }
}

function renderManager() {
  if (!managerState.entries.length) {
    managerDom.managerCategory.textContent = "沒有資料";
    managerDom.managerWord.textContent = "目前沒有可管理的候選圖";
    managerDom.managerQuery.textContent = "請確認 raw 候選圖與 seed 檔內容。";
    managerDom.candidateGrid.innerHTML = '<div class="candidate-card is-empty"><p>目前沒有候選圖片資料。</p></div>';
    managerDom.selectionSummary.innerHTML = '<p class="table-note">尚未建立任何管理項目。</p>';
    return;
  }

  const entry = managerState.entries[managerState.currentIndex];
  const selection = getSelection(entry);
  const completedCount = getCompletedCount();

  managerDom.managerCounter.textContent = `${managerState.currentIndex + 1} / ${managerState.entries.length}`;
  managerDom.selectionCounter.textContent = `已完成 ${completedCount} / ${managerState.entries.length}`;
  managerDom.managerCategory.textContent = entry.category;
  managerDom.managerWord.textContent = entry.word;
  managerDom.managerQuery.textContent = `搜尋字串：${entry.query} | 難度：${entry.level}`;
  managerDom.managerZhInput.value = selection.zh;

  renderCurrentApproved(entry);
  renderCandidateOptions(entry, selection.selectedOptionId);
  renderSelectionSummary();
  updateNavigationState();
}

function renderCurrentApproved(entry) {
  const approvedOption = entry.options.find((option) => option.isCurrentApproved);
  if (!approvedOption) {
    managerDom.currentApprovedImage.src = "";
    managerDom.currentApprovedImage.alt = "目前沒有已採用圖片";
    managerDom.currentApprovedMeta.textContent = "目前沒有已採用圖片，請直接從候選圖中挑選。";
    return;
  }

  managerDom.currentApprovedImage.src = approvedOption.image;
  managerDom.currentApprovedImage.alt = `目前題庫圖片：${entry.word}`;
  managerDom.currentApprovedMeta.textContent = `${approvedOption.label} | ${approvedOption.source} | ${approvedOption.photographer || "未提供作者"}`;
}

function renderCandidateOptions(entry, selectedOptionId) {
  managerDom.candidateGrid.innerHTML = "";

  for (let index = 0; index < MAX_DISPLAY_OPTIONS; index += 1) {
    const option = entry.options[index];
    if (!option) {
      managerDom.candidateGrid.appendChild(createEmptyCandidateCard(index));
      continue;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = `candidate-card${selectedOptionId === option.optionId ? " is-selected" : ""}`;
    button.innerHTML = `
      <div class="candidate-frame">
        <img src="${option.image}" alt="${entry.word} 候選圖 ${index + 1}">
      </div>
      <div class="candidate-meta">
        <span class="candidate-tag">${option.label}</span>
        <h3>${option.source}</h3>
        <p class="table-note">${option.photographer || "未提供作者"}</p>
        <p class="table-note">${option.license}</p>
      </div>
    `;
    button.addEventListener("click", () => selectOption(entry, option));
    managerDom.candidateGrid.appendChild(button);
  }

  // 5th slot: upload
  managerDom.candidateGrid.appendChild(createUploadCandidateCard(entry, selectedOptionId));
}

function createEmptyCandidateCard(index) {
  const card = document.createElement("div");
  card.className = "candidate-card is-empty";
  card.innerHTML = `
    <div class="candidate-frame"></div>
    <div class="candidate-meta">
      <span class="candidate-tag">候選圖 ${index + 1}</span>
      <h3>目前沒有圖片</h3>
      <p class="table-note">這一題目前不足四張候選圖。若要補齊，請再下載更多 raw 圖片。</p>
    </div>
  `;
  return card;
}

function createUploadCandidateCard(entry, selectedOptionId) {
  const uploadedImg = managerState.uploadedImages[makeEntryKey(entry)];
  const uploadOptId = "upload::" + makeEntryKey(entry);
  const isSelected = selectedOptionId === uploadOptId;

  const card = document.createElement("button");
  card.type = "button";
  card.className = `candidate-card upload-card${isSelected ? " is-selected" : ""}`;

  if (uploadedImg) {
    card.innerHTML = `
      <div class="candidate-frame">
        <img src="${uploadedImg.dataUrl}" alt="自行上傳">
      </div>
      <div class="candidate-meta">
        <span class="candidate-tag">已上傳</span>
        <h3>自行上傳</h3>
        <p class="table-note">${uploadedImg.fileName}</p>
        <p class="table-note">Personal Use Only</p>
        <button type="button" class="ghost-button upload-replace-btn">更換圖片</button>
      </div>
    `;
    card.addEventListener("click", (e) => {
      if (e.target.closest(".upload-replace-btn")) {
        triggerUpload(entry);
        return;
      }
      const option = buildUploadOption(entry, uploadedImg);
      selectOption(entry, option);
    });
  } else {
    card.innerHTML = `
      <div class="candidate-frame upload-placeholder">
        <span class="upload-icon">⬆️</span>
      </div>
      <div class="candidate-meta">
        <span class="candidate-tag">自行上傳</span>
        <h3>點擊上傳圖片</h3>
        <p class="table-note">支援 JPG、PNG、WEBP</p>
        <p class="table-note">Personal Use Only</p>
      </div>
    `;
    card.addEventListener("click", () => triggerUpload(entry));
  }

  return card;
}

function triggerUpload(entry) {
  managerDom.uploadInput._targetEntry = entry;
  managerDom.uploadInput.value = "";
  managerDom.uploadInput.click();
}

function handleFileSelected(event) {
  const file = event.target.files[0];
  const entry = managerDom.uploadInput._targetEntry;
  if (!file || !entry) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    const dataUrl = e.target.result;
    const key = makeEntryKey(entry);
    managerState.uploadedImages[key] = { dataUrl, fileName: file.name };
    saveUploadedImages();
    // Auto-select the uploaded image
    const option = buildUploadOption(entry, managerState.uploadedImages[key]);
    selectOption(entry, option);
    renderManager();
  };
  reader.readAsDataURL(file);
}

function buildUploadOption(entry, uploadedImg) {
  return {
    optionId: "upload::" + makeEntryKey(entry),
    image: uploadedImg.dataUrl,
    label: "已上傳",
    source: "自行上傳",
    photographer: uploadedImg.fileName,
    license: "Personal Use Only",
    isCurrentApproved: false
  };
}

function loadUploadedImages() {
  try {
    const raw = localStorage.getItem(UPLOAD_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveUploadedImages() {
  try {
    localStorage.setItem(UPLOAD_STORAGE_KEY, JSON.stringify(managerState.uploadedImages));
  } catch (e) {
    console.warn("Could not save uploaded images to localStorage", e);
  }
}

function selectOption(entry, option) {
  const selection = getSelection(entry);
  selection.selectedOptionId = option.optionId;
  selection.selectedOption = option;
  saveSelections();
  renderManager();
}

function handleZhInput(event) {
  const entry = managerState.entries[managerState.currentIndex];
  const selection = getSelection(entry);
  selection.zh = event.target.value.trim();
  saveSelections();
  renderSelectionSummary();
  updateNavigationState();
}

function moveEntry(offset) {
  const nextIndex = managerState.currentIndex + offset;
  if (nextIndex < 0 || nextIndex >= managerState.entries.length) {
    return;
  }

  managerState.currentIndex = nextIndex;
  renderManager();
}

function exportSelections() {
  const selections = managerState.entries
    .map((entry) => {
      const selection = getSelection(entry);
      if (!selection.selectedOption) {
        return null;
      }

      return {
        word: entry.word,
        category: entry.category,
        query: entry.query,
        level: entry.level,
        zh: selection.zh,
        selectedOptionId: selection.selectedOptionId,
        selectedOption: selection.selectedOption
      };
    })
    .filter(Boolean);

  if (!selections.length) {
    window.alert("請至少先選一張圖片，再匯出選擇檔。");
    return;
  }

  const payload = {
    exportedAt: new Date().toISOString(),
    totalEntries: managerState.entries.length,
    completedEntries: selections.length,
    selections
  };
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  downloadManagerFile(`manager_selection_${stamp}.json`, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
}

function resetSelections() {
  const shouldReset = window.confirm("要清除題庫管理頁目前保存在瀏覽器中的所有選擇嗎？");
  if (!shouldReset) {
    return;
  }

  managerState.selections = {};
  saveSelections();
  renderManager();
}

function renderSelectionSummary() {
  const completed = managerState.entries
    .map((entry) => ({ entry, selection: getSelection(entry) }))
    .filter(({ selection }) => Boolean(selection.selectedOption))
    .slice(-8)
    .reverse();

  if (!completed.length) {
    managerDom.selectionSummary.innerHTML = '<p class="table-note">目前還沒有已選圖片。</p>';
    return;
  }

  const container = document.createElement("div");
  container.className = "selection-summary-list";

  completed.forEach(({ entry, selection }) => {
    const row = document.createElement("div");
    row.className = "selection-summary-item";
    row.innerHTML = `
      <div>
        <strong>${entry.word}</strong>
        <div class="table-note">中文：${selection.zh || "尚未填寫"}</div>
      </div>
      <div class="table-note">${selection.selectedOption.label}</div>
    `;
    container.appendChild(row);
  });

  managerDom.selectionSummary.innerHTML = "";
  managerDom.selectionSummary.appendChild(container);
}

function updateNavigationState() {
  managerDom.prevEntry.disabled = managerState.currentIndex === 0;
  managerDom.nextEntry.disabled = managerState.currentIndex >= managerState.entries.length - 1;
}

function getSelection(entry) {
  const key = makeEntryKey(entry);
  if (!managerState.selections[key]) {
    managerState.selections[key] = {
      word: entry.word,
      category: entry.category,
      zh: entry.zh || "",
      selectedOptionId: "",
      selectedOption: null
    };
  }
  return managerState.selections[key];
}

function getCompletedCount() {
  return managerState.entries.reduce((count, entry) => {
    const selection = getSelection(entry);
    return count + (selection.selectedOption ? 1 : 0);
  }, 0);
}

function makeEntryKey(entry) {
  return `${entry.category}::${entry.word}`;
}

function saveSelections() {
  try {
    window.localStorage.setItem(MANAGER_STORAGE_KEY, JSON.stringify(managerState.selections));
  } catch (error) {
    console.warn("Could not save manager selections", error);
  }
}

function loadManagerState() {
  try {
    const raw = window.localStorage.getItem(MANAGER_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (error) {
    console.warn("Could not load manager selections", error);
    return {};
  }
}

function downloadManagerFile(filename, content, mimeType) {
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