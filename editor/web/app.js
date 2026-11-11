/**
 * Touchgrind Skate 2 - Web Save Editor Client
 * Vanilla JavaScript (zero external framework dependencies)
 */

document.addEventListener("DOMContentLoaded", () => {
  let activeSessionId = null;
  let activeSessionData = null;
  let currentRawOffset = 0;
  const RAW_LIMIT = 50;

  // DOM Elements
  const statusLed = document.getElementById("status-led");
  const statusText = document.getElementById("status-text");
  const currentSessionIdSpan = document.getElementById("current-session-id");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const btnLoadSample = document.getElementById("btn-load-sample");
  const btnExport = document.getElementById("btn-export");
  const btnRecalcHmac = document.getElementById("btn-recalc-hmac");

  // Tab Elements
  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  // --------------------------------------------------------------------------
  // Tab Navigation Routing
  // --------------------------------------------------------------------------
  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      tabContents.forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      const targetContent = document.getElementById(targetId);
      if (targetContent) {
        targetContent.classList.add("active");
      }
      if (targetId === "tab-raw" && activeSessionId) {
        loadRawTable();
      } else if (targetId === "tab-replays" && activeSessionId) {
        loadReplays();
      }
    });
  });

  // --------------------------------------------------------------------------
  // Status and Notifications
  // --------------------------------------------------------------------------
  function setStatus(text, isError = false) {
    if (statusText) statusText.textContent = text.toUpperCase();
    if (statusLed) {
      statusLed.className = "led " + (isError ? "led-red" : "led-green");
    }
  }

  // Prevent browser window from navigating to dropped files outside the dropzone
  window.addEventListener("dragenter", (e) => e.preventDefault());
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("dragleave", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  // --------------------------------------------------------------------------
  // Drag-and-Drop & File Upload
  // --------------------------------------------------------------------------
  if (dropzone) {
    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("dragover");
      });
    });

    dropzone.addEventListener("drop", (e) => {
      const dt = e.dataTransfer;
      const files = dt ? dt.files : null;
      if (files && files.length > 0) {
        handleFiles(files);
      }
    });

    dropzone.addEventListener("click", () => {
      if (fileInput) fileInput.click();
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        handleFiles(files);
      }
    });
  }

  async function handleFiles(files) {
    setStatus("UPLOADING FILES...");
    try {
      if (!activeSessionId) {
        const createRes = await fetch("/api/session/create", { method: "POST" });
        const createData = await createRes.json();
        activeSessionId = createData.session_id;
      }

      // Check if ZIP archive uploaded
      let zipFile = null;
      for (let i = 0; i < files.length; i++) {
        if (files[i].name.toLowerCase().endsWith(".zip")) {
          zipFile = files[i];
          break;
        }
      }

      if (zipFile) {
        const formData = new FormData();
        formData.append("file", zipFile);
        const res = await fetch(`/api/session/${activeSessionId}/upload`, {
          method: "POST",
          body: formData,
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.message || errData.error || "ZIP Upload failed");
        }
      } else {
        // Upload individual loose files
        for (let i = 0; i < files.length; i++) {
          const file = files[i];
          const buffer = await file.arrayBuffer();
          const res = await fetch(`/api/session/${activeSessionId}/upload_file?filename=${encodeURIComponent(file.name)}`, {
            method: "POST",
            headers: {
              "Content-Type": "application/octet-stream",
              "X-Filename": file.name,
            },
            body: buffer,
          });
          if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.message || errData.error || `Upload failed for ${file.name}`);
          }
        }
      }

      setSessionActive(activeSessionId);
      await refreshSessionData();
      setStatus("SAVE LOADED SUCCESSFULLY");
    } catch (err) {
      console.error(err);
      setStatus("UPLOAD ERROR: " + err.message, true);
    }
  }

  // --------------------------------------------------------------------------
  // Sample Save Loading
  // --------------------------------------------------------------------------
  if (btnLoadSample) {
    btnLoadSample.addEventListener("click", async () => {
      setStatus("LOADING REFERENCE SAVE...");
      try {
        const res = await fetch("/api/session/load_sample", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!res.ok) throw new Error("Failed to load sample save");
        const data = await res.json();
        activeSessionId = data.session_id;
        setSessionActive(activeSessionId);
        await refreshSessionData();
        setStatus("REFERENCE SAVE LOADED");
      } catch (err) {
        console.error(err);
        setStatus("ERROR LOADING SAMPLE: " + err.message, true);
      }
    });
  }

  function setSessionActive(sid) {
    if (currentSessionIdSpan) {
      currentSessionIdSpan.textContent = sid;
    }
    if (btnExport) btnExport.disabled = false;
    if (btnRecalcHmac) btnRecalcHmac.disabled = false;
  }

  // --------------------------------------------------------------------------
  // Export Save Archive
  // --------------------------------------------------------------------------
  if (btnExport) {
    btnExport.addEventListener("click", () => {
      if (!activeSessionId) return;
      window.location.href = `/api/session/${activeSessionId}/export?format=iph1`;
      setStatus("EXPORT ARCHIVE GENERATED");
    });
  }

  // --------------------------------------------------------------------------
  // Refresh & Render All Data
  // --------------------------------------------------------------------------
  async function refreshSessionData() {
    if (!activeSessionId) return;
    try {
      const res = await fetch(`/api/session/${activeSessionId}/data`);
      if (!res.ok) throw new Error("Failed to fetch session data");
      activeSessionData = await res.json();

      renderParks(activeSessionData.parks || {});
      renderChallenges(activeSessionData.challenges || []);
      renderHighscores(activeSessionData.highscores || []);
      renderEquipment(activeSessionData.equipment || {});
      renderCloud(activeSessionData.cloud || {});
      renderTextures(activeSessionData.textures || []);
      loadReplays();
    } catch (err) {
      console.error(err);
      setStatus("REFRESH FAILED: " + err.message, true);
    }
  }

  // --------------------------------------------------------------------------
  // Tab 1: Parks & DLC Rendering
  // --------------------------------------------------------------------------
  const parksContainer = document.getElementById("parks-container");
  const btnUnlockAllParks = document.getElementById("btn-unlock-all-parks");

  const PARK_NAMES_MAP = {
    thecarpark: "The Car Park",
    dairyfactory: "Dairy Factory",
    thedocks: "The Docks",
    themotel: "The Motel",
    playground: "Playground",
    megaramp: "Mega Ramp",
    spacedock: "Space Dock",
    theoffice: "The Office",
  };

  function renderParks(parks) {
    if (!parksContainer) return;
    parksContainer.innerHTML = "";
    Object.keys(PARK_NAMES_MAP).forEach((key) => {
      const isUnlocked = Boolean(parks[key]);
      const card = document.createElement("div");
      card.className = "switch-control";
      card.innerHTML = `
        <span class="switch-label">${PARK_NAMES_MAP[key]}</span>
        <label class="switch">
          <input type="checkbox" data-park="${key}" ${isUnlocked ? "checked" : ""}>
          <span class="slider"></span>
        </label>
      `;
      const input = card.querySelector("input");
      input.addEventListener("change", async (e) => {
        const payload = {};
        payload[key] = e.target.checked;
        await fetch(`/api/session/${activeSessionId}/registry/parks`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setStatus(`PARK ${PARK_NAMES_MAP[key]} ${e.target.checked ? "UNLOCKED" : "LOCKED"}`);
      });
      parksContainer.appendChild(card);
    });
  }

  if (btnUnlockAllParks) {
    btnUnlockAllParks.addEventListener("click", async () => {
      if (!activeSessionId) return;
      await fetch(`/api/session/${activeSessionId}/registry/parks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unlock_all: true }),
      });
      await refreshSessionData();
      setStatus("ALL PARKS UNLOCKED");
    });
  }

  // --------------------------------------------------------------------------
  // Tab 2: Challenges Rendering
  // --------------------------------------------------------------------------
  const selectChallengePark = document.getElementById("select-challenge-park");
  const challengesContainer = document.getElementById("challenges-container");
  const btnCompleteParkChallenges = document.getElementById("btn-complete-park-challenges");
  const btnResetParkChallenges = document.getElementById("btn-reset-park-challenges");
  const challengeSearchInput = document.getElementById("challenge-search-input");
  const challengesProgressLabel = document.getElementById("challenges-progress-label");

  let challengeCatalog = null;
  async function loadChallengeCatalog() {
    try {
      const res = await fetch("/api/challenges/catalog");
      if (res.ok) {
        challengeCatalog = await res.json();
        if (activeSessionData) renderChallenges();
      }
    } catch (e) {
      console.warn("Could not load challenge catalog:", e);
    }
  }
  loadChallengeCatalog();

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderChallenges() {
    if (!challengesContainer || !activeSessionData) return;
    const park = selectChallengePark ? selectChallengePark.value : "backyard";
    const challenges = activeSessionData.challenges || [];
    const parkChallenges = {};
    challenges.forEach((ch) => {
      if (ch.park === park) {
        parkChallenges[ch.challenge_id] = ch.completed;
      }
    });

    const catalogParkList = (challengeCatalog && challengeCatalog[park]) ? challengeCatalog[park] : null;
    const maxCount = catalogParkList ? catalogParkList.length : (park === "backyard" ? 25 : 45);

    let completedCount = 0;
    for (let cid = 1; cid <= maxCount; cid++) {
      if (parkChallenges[cid]) completedCount++;
    }

    if (challengesProgressLabel) {
      const pct = maxCount > 0 ? Math.round((completedCount / maxCount) * 100) : 0;
      challengesProgressLabel.textContent = `${completedCount} of ${maxCount} challenges completed (${pct}%)`;
    }

    const filterText = (challengeSearchInput ? challengeSearchInput.value : "").trim().toLowerCase();

    challengesContainer.innerHTML = "";
    let renderedCount = 0;

    for (let i = 0; i < maxCount; i++) {
      const cid = i + 1;
      const meta = catalogParkList ? catalogParkList[i] : null;
      const title = meta ? meta.title : `Challenge #${cid}`;
      const desc = meta ? (meta.description || meta.info || "No description available") : "In-game skatepark challenge";
      const info = meta ? meta.info : "";
      const duration = meta ? meta.duration : "";
      const reqs = (meta && meta.requirements) ? meta.requirements : [];

      if (filterText) {
        const fullSearchable = `${cid} ${title} ${desc} ${info} ${reqs.join(" ")}`.toLowerCase();
        if (!fullSearchable.includes(filterText)) {
          continue;
        }
      }

      renderedCount++;
      const isCompleted = Boolean(parkChallenges[cid]);
      const item = document.createElement("div");
      item.className = `challenge-item challenge-card ${isCompleted ? "completed" : ""}`;

      let tagsHtml = "";
      if (duration) {
        tagsHtml += `<span class="challenge-tag">${escapeHtml(duration)}</span>`;
      }
      reqs.forEach((r) => {
        tagsHtml += `<span class="challenge-tag">${escapeHtml(r)}</span>`;
      });
      if (info && !tagsHtml) {
        tagsHtml += `<span class="challenge-tag">${escapeHtml(info)}</span>`;
      }

      item.innerHTML = `
        <div class="challenge-card-header">
          <span class="challenge-id challenge-card-num">#${cid}</span>
          <span class="challenge-card-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
          <span class="challenge-status challenge-status-badge ${isCompleted ? "status-done" : "status-locked"}">${isCompleted ? "DONE" : "LOCKED"}</span>
        </div>
        <div class="challenge-card-desc">${escapeHtml(desc)}</div>
        <div class="challenge-card-footer">
          <div class="challenge-meta-tags">${tagsHtml}</div>
          <label class="switch" style="margin-left: auto;">
            <input type="checkbox" ${isCompleted ? "checked" : ""}>
            <span class="slider"></span>
          </label>
        </div>
      `;

      item.addEventListener("click", async (e) => {
        if (!activeSessionId) return;
        const newStatus = isCompleted ? 0 : 1;
        await fetch(`/api/session/${activeSessionId}/registry/challenge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ park: park, challenge_id: cid, completed: newStatus }),
        });
        await refreshSessionData();
        setStatus(`CHALLENGE #${cid} (${title}) ${newStatus ? "UNLOCKED" : "LOCKED"}`);
      });

      challengesContainer.appendChild(item);
    }

    if (renderedCount === 0) {
      challengesContainer.innerHTML = `<div style="grid-column: 1 / -1; padding: 2rem; text-align: center; color: #8b929c;">No challenges found matching "${escapeHtml(filterText)}" in ${park.toUpperCase()}.</div>`;
    }
  }

  if (selectChallengePark) {
    selectChallengePark.addEventListener("change", renderChallenges);
  }

  if (challengeSearchInput) {
    challengeSearchInput.addEventListener("input", renderChallenges);
  }

  if (btnCompleteParkChallenges) {
    btnCompleteParkChallenges.addEventListener("click", async () => {
      if (!activeSessionId || !selectChallengePark) return;
      const park = selectChallengePark.value;
      const catalogParkList = (challengeCatalog && challengeCatalog[park]) ? challengeCatalog[park] : null;
      const maxCount = catalogParkList ? catalogParkList.length : (park === "backyard" ? 25 : 45);
      setStatus(`COMPLETING ALL ${maxCount} CHALLENGES FOR ${park.toUpperCase()}...`);
      for (let cid = 1; cid <= maxCount; cid++) {
        await fetch(`/api/session/${activeSessionId}/registry/challenge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ park: park, challenge_id: cid, completed: 1 }),
        });
      }
      await refreshSessionData();
      setStatus(`ALL ${maxCount} CHALLENGES COMPLETED FOR ${park.toUpperCase()}`);
    });
  }

  if (btnResetParkChallenges) {
    btnResetParkChallenges.addEventListener("click", async () => {
      if (!activeSessionId || !selectChallengePark) return;
      const park = selectChallengePark.value;
      const catalogParkList = (challengeCatalog && challengeCatalog[park]) ? challengeCatalog[park] : null;
      const maxCount = catalogParkList ? catalogParkList.length : (park === "backyard" ? 25 : 45);
      setStatus(`LOCKING ALL ${maxCount} CHALLENGES FOR ${park.toUpperCase()}...`);
      for (let cid = 1; cid <= maxCount; cid++) {
        await fetch(`/api/session/${activeSessionId}/registry/challenge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ park: park, challenge_id: cid, completed: 0 }),
        });
      }
      await refreshSessionData();
      setStatus(`ALL ${maxCount} CHALLENGES LOCKED FOR ${park.toUpperCase()}`);
    });
  }

  // --------------------------------------------------------------------------
  // Tab 3: High Scores Rendering
  // --------------------------------------------------------------------------
  const scoresTableBody = document.getElementById("scores-table-body");
  const PARK_ID_NAMES = [
    "Backyard",
    "The Docks",
    "Dairy Factory",
    "The Car Park",
    "Downhill",
    "Funpark",
    "Office",
    "Research",
    "Space Dock",
  ];

  function renderHighscores(scores) {
    if (!scoresTableBody) return;
    scoresTableBody.innerHTML = "";
    scores.forEach((s) => {
      const pid = s.park_id;
      const parkName = PARK_ID_NAMES[pid] || `Park ${pid}`;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${pid}</td>
        <td><strong>${parkName}</strong></td>
        <td><input type="number" class="metal-input score-comp" value="${s.competition || 0}" min="0"></td>
        <td><input type="number" class="metal-input score-line" value="${s.line || 0}" min="0"></td>
        <td><button type="button" class="btn btn-silver btn-small btn-save-score">Save</button></td>
      `;
      const btnSave = tr.querySelector(".btn-save-score");
      btnSave.addEventListener("click", async () => {
        if (!activeSessionId) return;
        const comp = parseInt(tr.querySelector(".score-comp").value, 10);
        const line = parseInt(tr.querySelector(".score-line").value, 10);
        await fetch(`/api/session/${activeSessionId}/registry/highscore`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ park_id: pid, competition: comp, line: line }),
        });
        setStatus(`HIGHSCORES SAVED FOR ${parkName.toUpperCase()}`);
      });
      scoresTableBody.appendChild(tr);
    });
  }

  // --------------------------------------------------------------------------
  // Tab 4: Equipment & Stats Rendering
  // --------------------------------------------------------------------------
  const eqBoardIdx = document.getElementById("eq-board-idx");
  const eqDeckIdx = document.getElementById("eq-deck-idx");
  const eqGripIdx = document.getElementById("eq-grip-idx");
  const eqWheelIdx = document.getElementById("eq-wheel-idx");
  const eqWearTime = document.getElementById("eq-wear-time");
  const btnSaveEquipment = document.getElementById("btn-save-equipment");

  function renderEquipment(eq) {
    if (eqBoardIdx) eqBoardIdx.value = eq.currentBoardIndex ?? 0;
    if (eqDeckIdx) eqDeckIdx.value = eq.currentDeckIndex ?? 0;
    if (eqGripIdx) eqGripIdx.value = eq.currentGriptapeIndex ?? 0;
    if (eqWheelIdx) eqWheelIdx.value = eq.currentWheelIndex ?? 0;
    if (eqWearTime) eqWearTime.value = (eq.deck_wear_time ?? 0).toFixed(1);
  }

  if (btnSaveEquipment) {
    btnSaveEquipment.addEventListener("click", async () => {
      if (!activeSessionId) return;
      const payload = {
        currentBoardIndex: parseInt(eqBoardIdx.value, 10),
        currentDeckIndex: parseInt(eqDeckIdx.value, 10),
        currentGriptapeIndex: parseInt(eqGripIdx.value, 10),
        currentWheelIndex: parseInt(eqWheelIdx.value, 10),
        deck_wear_time: parseFloat(eqWearTime.value),
      };
      const res = await fetch(`/api/session/${activeSessionId}/registry/equipment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setStatus("EQUIPMENT SETUP SAVED");
      } else {
        const err = await res.json();
        setStatus("EQUIPMENT SAVE ERROR: " + (err.message || "Failed"), true);
      }
    });
  }

  // --------------------------------------------------------------------------
  // Tab 5: Board Textures Rendering
  // --------------------------------------------------------------------------
  const texturesContainer = document.getElementById("textures-container");

  function renderTextures(textures) {
    if (!texturesContainer) return;
    texturesContainer.innerHTML = "";
    textures.forEach((tex) => {
      const card = document.createElement("div");
      card.className = "texture-card";
      const previewUrl = `/api/session/${activeSessionId}/textures/preview?file=${encodeURIComponent(tex.filename)}`;
      card.innerHTML = `
        <div class="texture-preview-box">
          <img src="${previewUrl}" alt="${tex.filename}">
        </div>
        <div class="texture-meta">
          <div class="texture-name">${tex.filename}</div>
          <div>${tex.width}x${tex.height} (${tex.format ? tex.format.toUpperCase() : ""}) - ${(tex.size / 1024).toFixed(1)} KB</div>
        </div>
        <div class="action-group">
          <label class="btn btn-silver btn-small" style="cursor: pointer;">
            Replace
            <input type="file" style="display: none;" class="tex-file-input" accept=".png,.jpg,.jpeg">
          </label>
          <a href="${previewUrl}" download="${tex.filename}" class="btn btn-metal btn-small">Download</a>
        </div>
      `;
      const texInput = card.querySelector(".tex-file-input");
      texInput.addEventListener("change", async (e) => {
        const f = e.target.files[0];
        if (!f) return;
        setStatus(`REPLACING ${tex.filename}...`);
        const buf = await f.arrayBuffer();
        const res = await fetch(`/api/session/${activeSessionId}/textures/replace?filename=${encodeURIComponent(tex.filename)}`, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: buf,
        });
        if (res.ok) {
          setStatus(`${tex.filename} REPLACED SUCCESSFULLY`);
          await refreshSessionData();
        } else {
          const err = await res.json();
          setStatus("TEXTURE ERROR: " + (err.message || "Failed"), true);
        }
      });
      texturesContainer.appendChild(card);
    });
  }

  // --------------------------------------------------------------------------
  // Tab 6: Replay Vault & Clipcounter
  // --------------------------------------------------------------------------
  const replaysTableBody = document.getElementById("replays-table-body");
  const clipcounterParkSelect = document.getElementById("clipcounter-park-select");
  const clipcounterInput = document.getElementById("clipcounter-input");
  const btnUpdateClipcounter = document.getElementById("btn-update-clipcounter");

  async function loadReplays() {
    if (!activeSessionId || !replaysTableBody) return;
    try {
      const res = await fetch(`/api/session/${activeSessionId}/replays`);
      if (!res.ok) return;
      const data = await res.json();
      replaysTableBody.innerHTML = "";
      (data.replays || []).forEach((r) => {
        const tr = document.createElement("tr");
        const dateStr = new Date(r.timestamp * 1000).toLocaleString();
        tr.innerHTML = `
          <td><strong>${r.park}</strong></td>
          <td><span class="badge ${r.folder === "top" ? "badge-valid" : ""}">${r.folder}</span></td>
          <td><code>${r.filename}</code></td>
          <td>${r.run_type}</td>
          <td>${(r.score || 0).toLocaleString()}</td>
          <td>${(r.duration || 0).toFixed(1)}s</td>
          <td><small>${dateStr}</small></td>
          <td>
            <button type="button" class="btn btn-silver btn-small btn-del-replay">Delete</button>
          </td>
        `;
        const btnDel = tr.querySelector(".btn-del-replay");
        btnDel.addEventListener("click", async () => {
          if (!confirm(`Delete replay ${r.filename}?`)) return;
          await fetch(`/api/session/${activeSessionId}/replays/${r.park}/${r.folder}/${r.filename}`, {
            method: "DELETE",
          });
          setStatus(`REPLAY ${r.filename} DELETED`);
          loadReplays();
        });
        replaysTableBody.appendChild(tr);
      });

      // Update clipcounter display
      if (clipcounterParkSelect) {
        updateClipcounterDisplay();
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function updateClipcounterDisplay() {
    if (!activeSessionId || !clipcounterParkSelect || !clipcounterInput) return;
    const park = clipcounterParkSelect.value;
    const res = await fetch(`/api/session/${activeSessionId}/replays/clipcounter?park=${park}`);
    if (res.ok) {
      const data = await res.json();
      clipcounterInput.value = data.clipcounter;
    }
  }

  if (clipcounterParkSelect) {
    clipcounterParkSelect.addEventListener("change", updateClipcounterDisplay);
  }

  if (btnUpdateClipcounter) {
    btnUpdateClipcounter.addEventListener("click", async () => {
      if (!activeSessionId || !clipcounterParkSelect || !clipcounterInput) return;
      const park = clipcounterParkSelect.value;
      const val = parseInt(clipcounterInput.value, 10);
      await fetch(`/api/session/${activeSessionId}/replays/clipcounter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ park: park, clipcounter: val }),
      });
      setStatus(`CLIPCOUNTER FOR ${park.toUpperCase()} UPDATED TO ${val}`);
    });
  }

  // --------------------------------------------------------------------------
  // Tab 7: CloudKit & Special Boards
  // --------------------------------------------------------------------------
  const cloudUserId = document.getElementById("cloud-user-id");
  const cloudUuid = document.getElementById("cloud-uuid");
  const btnSaveCloudUser = document.getElementById("btn-save-cloud-user");
  const hmacStatusBadge = document.getElementById("hmac-status-badge");
  const hmacDigestDisplay = document.getElementById("hmac-digest-display");
  const specialBoardsContainer = document.getElementById("special-boards-container");
  const btnSaveSpecialBoards = document.getElementById("btn-save-special-boards");
  const btnSelectAllBoards = document.getElementById("btn-select-all-boards");
  const btnClearAllBoards = document.getElementById("btn-clear-all-boards");

  let currentSpecialBoards = [];

  function renderCloud(cloud) {
    if (cloudUserId) cloudUserId.value = cloud.user_id || "";
    if (cloudUuid) cloudUuid.value = cloud.uuid || "";
    if (hmacDigestDisplay) hmacDigestDisplay.textContent = cloud.hmac || "NO HMAC";
    if (hmacStatusBadge) {
      hmacStatusBadge.className = "badge " + (cloud.hmac_valid ? "badge-valid" : "badge-invalid");
      hmacStatusBadge.textContent = cloud.hmac_valid ? "VALID" : "UNVERIFIED";
    }

    currentSpecialBoards = cloud.special_boards || [];
    renderSpecialBoardsGrid();
  }

  function renderSpecialBoardsGrid() {
    if (!specialBoardsContainer) return;
    specialBoardsContainer.innerHTML = "";
    for (let bid = 2; bid <= 31; bid++) {
      const isUnlocked = currentSpecialBoards.includes(bid);
      const div = document.createElement("div");
      div.className = `board-toggle ${isUnlocked ? "active" : ""}`;
      div.innerHTML = `
        <span class="board-id">#${bid}</span>
        <span class="board-label">${isUnlocked ? "UNLOCKED" : "LOCKED"}</span>
      `;
      div.addEventListener("click", () => {
        if (currentSpecialBoards.includes(bid)) {
          currentSpecialBoards = currentSpecialBoards.filter((b) => b !== bid);
        } else {
          currentSpecialBoards.push(bid);
          currentSpecialBoards.sort((a, b) => a - b);
        }
        renderSpecialBoardsGrid();
      });
      specialBoardsContainer.appendChild(div);
    }
  }

  if (btnSelectAllBoards) {
    btnSelectAllBoards.addEventListener("click", () => {
      currentSpecialBoards = [];
      for (let i = 2; i <= 31; i++) currentSpecialBoards.push(i);
      renderSpecialBoardsGrid();
    });
  }

  if (btnClearAllBoards) {
    btnClearAllBoards.addEventListener("click", () => {
      currentSpecialBoards = [];
      renderSpecialBoardsGrid();
    });
  }

  if (btnSaveSpecialBoards) {
    btnSaveSpecialBoards.addEventListener("click", async () => {
      if (!activeSessionId) return;
      setStatus("SAVING SPECIAL BOARDS...");
      const res = await fetch(`/api/session/${activeSessionId}/cloud/boards`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ boards: currentSpecialBoards }),
      });
      if (res.ok) {
        setStatus("SPECIAL BOARDS SAVED AND SIGNED");
        await refreshSessionData();
      }
    });
  }

  if (btnSaveCloudUser) {
    btnSaveCloudUser.addEventListener("click", async () => {
      if (!activeSessionId) return;
      const res = await fetch(`/api/session/${activeSessionId}/cloud/user`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: cloudUserId.value,
          uuid: cloudUuid.value,
        }),
      });
      if (res.ok) {
        setStatus("CLOUD IDENTIFIERS UPDATED");
        await refreshSessionData();
      } else {
        const err = await res.json();
        setStatus("ERROR: " + (err.message || "Invalid input"), true);
      }
    });
  }

  if (btnRecalcHmac) {
    btnRecalcHmac.addEventListener("click", async () => {
      if (!activeSessionId) return;
      setStatus("RECALCULATING HMAC-SHA256 SIGNATURE...");
      const res = await fetch(`/api/session/${activeSessionId}/cloud/recalculate_hmac`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        const data = await res.json();
        setStatus("HMAC SIGNATURE COMPUTED: " + data.hmac.substring(0, 16) + "...");
        await refreshSessionData();
      }
    });
  }

  // --------------------------------------------------------------------------
  // Tab 8: Raw DB Explorer
  // --------------------------------------------------------------------------
  const rawTableSelect = document.getElementById("raw-table-select");
  const rawSearchInput = document.getElementById("raw-search-input");
  const btnRawSearch = document.getElementById("btn-raw-search");
  const rawTableBody = document.getElementById("raw-table-body");
  const btnRawPrev = document.getElementById("btn-raw-prev");
  const btnRawNext = document.getElementById("btn-raw-next");
  const rawPageInfo = document.getElementById("raw-page-info");

  async function loadRawTable() {
    if (!activeSessionId || !rawTableBody) return;
    const table = rawTableSelect ? rawTableSelect.value : "integerdata";
    const search = rawSearchInput ? rawSearchInput.value.trim() : "";
    let url = `/api/session/${activeSessionId}/raw_db?table=${table}&limit=${RAW_LIMIT}&offset=${currentRawOffset}`;
    if (search) {
      url += `&search=${encodeURIComponent(search)}`;
    }

    try {
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      rawTableBody.innerHTML = "";
      (data.rows || []).forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${row.key}</code></td>
          <td><input type="text" class="metal-input raw-val" value="${row.value !== null ? row.value : ""}" style="width: 100%;"></td>
          <td>
            <button type="button" class="btn btn-silver btn-small btn-raw-save">Save</button>
            <button type="button" class="btn btn-metal btn-small btn-raw-del">Delete</button>
          </td>
        `;
        const btnSave = tr.querySelector(".btn-raw-save");
        btnSave.addEventListener("click", async () => {
          const newVal = tr.querySelector(".raw-val").value;
          let typedVal = newVal;
          if (table === "integerdata") typedVal = parseInt(newVal, 10);
          else if (table === "floatdata") typedVal = parseFloat(newVal);

          await fetch(`/api/session/${activeSessionId}/raw_db`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ table: table, action: "update", key: row.key, value: typedVal }),
          });
          setStatus(`KEY ${row.key} UPDATED`);
        });

        const btnDel = tr.querySelector(".btn-raw-del");
        btnDel.addEventListener("click", async () => {
          if (!confirm(`Delete key ${row.key}?`)) return;
          await fetch(`/api/session/${activeSessionId}/raw_db`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ table: table, action: "delete", key: row.key }),
          });
          setStatus(`KEY ${row.key} DELETED`);
          loadRawTable();
        });

        rawTableBody.appendChild(tr);
      });

      if (rawPageInfo) {
        const page = Math.floor(currentRawOffset / RAW_LIMIT) + 1;
        const totalPages = Math.ceil((data.total || 1) / RAW_LIMIT);
        rawPageInfo.textContent = `Page ${page} of ${totalPages} (${data.total || 0} rows)`;
      }
    } catch (err) {
      console.error(err);
    }
  }

  if (rawTableSelect) {
    rawTableSelect.addEventListener("change", () => {
      currentRawOffset = 0;
      loadRawTable();
    });
  }

  if (btnRawSearch) {
    btnRawSearch.addEventListener("click", () => {
      currentRawOffset = 0;
      loadRawTable();
    });
  }

  if (btnRawPrev) {
    btnRawPrev.addEventListener("click", () => {
      if (currentRawOffset >= RAW_LIMIT) {
        currentRawOffset -= RAW_LIMIT;
        loadRawTable();
      }
    });
  }

  if (btnRawNext) {
    btnRawNext.addEventListener("click", () => {
      currentRawOffset += RAW_LIMIT;
      loadRawTable();
    });
  }
});
