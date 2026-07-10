function nextPowerOfTwo(n) {
  let size = 1;
  while (size < n) size *= 2;
  return size;
}

function parseTeamsFromTextarea(text) {
  return text
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
}

function setupByePreparation() {
  const form = document.getElementById("create-bracket-form");
  if (!form) return;

  const teamsInput = document.getElementById("teams-input");
  const prepareBtn = document.getElementById("prepare-byes");
  const summary = document.getElementById("bye-summary");
  const gateMessage = document.getElementById("bye-gate-message");
  const list = document.getElementById("bye-selector");
  const generateBtn = document.getElementById("generate-bracket");

  function getRequiredByes(teams) {
    if (teams.length < 2) return 0;
    const size = nextPowerOfTwo(teams.length);
    return size - teams.length;
  }

  function setGate(canGenerate, message, state = "warning") {
    if (generateBtn) generateBtn.disabled = !canGenerate;
    if (!gateMessage) return;
    gateMessage.textContent = message;
    gateMessage.dataset.state = state;
  }

  function evaluateGate() {
    const teams = parseTeamsFromTextarea(teamsInput.value);
    const requiredByes = getRequiredByes(teams);
    const preparedFor = list.dataset.preparedFor || "";
    const currentKey = teams.join("|");
    const checked = list.querySelectorAll("input[type='checkbox']:checked").length;

    if (teams.length < 2) {
      setGate(true, "Add at least two teams to generate a bracket.", "warning");
      return;
    }

    if (requiredByes === 0) {
      setGate(true, "No BYEs needed for this team count.", "ok");
      return;
    }

    if (preparedFor !== currentKey) {
      setGate(false, `This bracket needs ${requiredByes} BYE(s). Click Prepare BYEs first.`, "warning");
      return;
    }

    if (checked !== requiredByes) {
      setGate(false, `Select exactly ${requiredByes} BYE team(s) before generating.`, "warning");
      return;
    }

    setGate(true, "BYE selections complete. You can generate the bracket.", "ok");
  }

  function updateSummaryAndLimit(requiredByes) {
    const checked = list.querySelectorAll("input[type='checkbox']:checked").length;
    summary.textContent =
      requiredByes > 0
        ? `Bracket needs ${requiredByes} BYEs. Selected ${checked}/${requiredByes}.`
        : "No BYEs needed for this team count.";

    const checkboxes = Array.from(list.querySelectorAll("input[type='checkbox']"));
    checkboxes.forEach((cb) => {
      if (!cb.checked) cb.disabled = checked >= requiredByes && requiredByes > 0;
    });

    evaluateGate();
  }

  prepareBtn.addEventListener("click", () => {
    const teams = parseTeamsFromTextarea(teamsInput.value);

    if (teams.length < 2) {
      summary.textContent = "Add at least two teams first.";
      list.innerHTML = "";
      return;
    }

    const size = nextPowerOfTwo(teams.length);
    const requiredByes = size - teams.length;
    list.dataset.preparedFor = teams.join("|");

    list.innerHTML = "";
    teams.forEach((team) => {
      const id = `bye-${team.replace(/\s+/g, "-").toLowerCase()}`;
      const row = document.createElement("label");
      row.className = "bye-item";
      row.innerHTML = `<input type="checkbox" id="${id}" name="bye_teams" value="${team}"> <span>${team}</span>`;
      list.appendChild(row);
    });

    updateSummaryAndLimit(requiredByes);
    list.onchange = () => updateSummaryAndLimit(requiredByes);
  });

  teamsInput.addEventListener("input", () => {
    evaluateGate();
  });

  form.addEventListener("submit", (event) => {
    evaluateGate();
    if (generateBtn && generateBtn.disabled) {
      event.preventDefault();
      setFeedback("Select required BYEs before generating the bracket.", "error");
    }
  });

  evaluateGate();
}

function setFeedback(message, state = "info") {
  const actionFeedback = document.getElementById("action-feedback");
  if (!actionFeedback) return;
  actionFeedback.innerHTML = "";
  actionFeedback.textContent = message;
  actionFeedback.dataset.state = state;
}

function setFeedbackWithUndo(message, onUndo) {
  const actionFeedback = document.getElementById("action-feedback");
  if (!actionFeedback) return;

  actionFeedback.innerHTML = "";
  const text = document.createElement("span");
  text.textContent = message;
  actionFeedback.appendChild(text);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "feedback-inline-btn";
  btn.textContent = "Undo";
  btn.addEventListener("click", onUndo);
  actionFeedback.appendChild(btn);

  actionFeedback.dataset.state = "success";
}

function layoutRounds(roundsBoard) {
  const cols = Array.from(roundsBoard.querySelectorAll(".round-column"));
  if (cols.length === 0) return;

  const firstRoundMatches = cols[0].querySelectorAll(".match");
  if (firstRoundMatches.length === 0) return;

  const matchHeight = firstRoundMatches[0].offsetHeight || 96;
  const baseGap = 16;
  const titleAllowance = 44;
  const minBoardHeight = 420;

  const firstRoundHeight =
    firstRoundMatches.length * matchHeight +
    Math.max(0, firstRoundMatches.length - 1) * baseGap +
    titleAllowance;

  const boardHeight = Math.max(minBoardHeight, firstRoundHeight);
  roundsBoard.style.setProperty("--board-height", `${boardHeight}px`);

  cols.forEach((col) => {
    const matchesWrap = col.querySelector(".round-matches");
    if (!matchesWrap) return;

    const matches = matchesWrap.querySelectorAll(".match");
    const count = matches.length;
    if (count <= 1) {
      matchesWrap.style.rowGap = "0px";
      matchesWrap.style.paddingTop = "0px";
      return;
    }

    const available = Math.max(0, boardHeight - titleAllowance - count * matchHeight);
    const gap = Math.max(baseGap, available / (count - 1));
    matchesWrap.style.rowGap = `${gap}px`;
    matchesWrap.style.paddingTop = "0px";
  });
}

function setupBoardScrollEnhancements(roundsBoard) {
  if (!roundsBoard || roundsBoard.dataset.scrollEnhanced === "1") return;
  roundsBoard.dataset.scrollEnhanced = "1";

  // Let mouse-wheel users scroll wide brackets horizontally without holding Shift.
  roundsBoard.addEventListener(
    "wheel",
    (event) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      if (roundsBoard.scrollWidth <= roundsBoard.clientWidth) return;

      event.preventDefault();
      roundsBoard.scrollLeft += event.deltaY;
    },
    { passive: false }
  );
}

function setupBoardDragPan(roundsBoard) {
  if (!roundsBoard || roundsBoard.dataset.dragPan === "1") return;
  roundsBoard.dataset.dragPan = "1";

  let isDown = false;
  let startX = 0;
  let startScrollLeft = 0;
  let moved = false;

  roundsBoard.addEventListener("mousedown", (event) => {
    const target = event.target;
    if (target.closest("button, a, input, select, textarea, label")) return;

    isDown = true;
    moved = false;
    startX = event.pageX;
    startScrollLeft = roundsBoard.scrollLeft;
    roundsBoard.classList.add("dragging");
  });

  window.addEventListener("mouseup", () => {
    isDown = false;
    roundsBoard.classList.remove("dragging");
  });

  roundsBoard.addEventListener("mouseleave", () => {
    isDown = false;
    roundsBoard.classList.remove("dragging");
  });

  roundsBoard.addEventListener("mousemove", (event) => {
    if (!isDown) return;
    const walk = event.pageX - startX;
    if (Math.abs(walk) > 2) moved = true;
    roundsBoard.scrollLeft = startScrollLeft - walk;
  });

  roundsBoard.addEventListener(
    "click",
    (event) => {
      if (!moved) return;
      event.preventDefault();
      event.stopPropagation();
      moved = false;
    },
    true
  );
}

function setupBoardZoomControls(roundsBoard, onAfterZoom) {
  if (!roundsBoard || roundsBoard.dataset.zoomReady === "1") return;
  roundsBoard.dataset.zoomReady = "1";

  const zoomInBtn = document.getElementById("zoom-in");
  const zoomOutBtn = document.getElementById("zoom-out");
  if (!zoomInBtn || !zoomOutBtn) return;

  const minZoom = 0.75;
  const maxZoom = 1.35;
  const step = 0.05;
  let zoomLevel = 1;

  function applyZoom(nextZoom) {
    zoomLevel = Math.max(minZoom, Math.min(maxZoom, nextZoom));
    roundsBoard.style.setProperty("--board-zoom", String(zoomLevel));
    if (typeof onAfterZoom === "function") {
      onAfterZoom();
    }
  }

  zoomInBtn.addEventListener("click", () => applyZoom(zoomLevel + step));
  zoomOutBtn.addEventListener("click", () => applyZoom(zoomLevel - step));

  roundsBoard.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    if (event.deltaY < 0) {
      applyZoom(zoomLevel + step);
    } else if (event.deltaY > 0) {
      applyZoom(zoomLevel - step);
    }
  }, { passive: false });
}

function drawConnectors(roundsBoard) {
  const existing = roundsBoard.querySelector(".connector-layer");
  if (existing) existing.remove();

  const cols = Array.from(roundsBoard.querySelectorAll(".round-column"));
  if (cols.length < 2) return;

  const width = roundsBoard.scrollWidth;
  const height = roundsBoard.scrollHeight;
  const boardRect = roundsBoard.getBoundingClientRect();

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("connector-layer");
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.style.width = `${width}px`;
  svg.style.height = `${height}px`;

  for (let roundIndex = 0; roundIndex < cols.length - 1; roundIndex += 1) {
    const currentMatches = Array.from(cols[roundIndex].querySelectorAll(".match"));
    const nextMatches = Array.from(cols[roundIndex + 1].querySelectorAll(".match"));

    currentMatches.forEach((matchEl, matchIndex) => {
      const nextMatch = nextMatches[Math.floor(matchIndex / 2)];
      if (!nextMatch) return;

      const fromRect = matchEl.getBoundingClientRect();
      const toRect = nextMatch.getBoundingClientRect();

      const fromX = fromRect.right - boardRect.left + roundsBoard.scrollLeft;
      const fromY = fromRect.top - boardRect.top + roundsBoard.scrollTop + fromRect.height / 2;
      const toX = toRect.left - boardRect.left + roundsBoard.scrollLeft;
      const toY = toRect.top - boardRect.top + roundsBoard.scrollTop + toRect.height / 2;
      const midX = fromX + (toX - fromX) / 2;

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M ${fromX} ${fromY} L ${midX} ${fromY} L ${midX} ${toY} L ${toX} ${toY}`);
      svg.appendChild(path);
    });
  }

  roundsBoard.prepend(svg);
}

function renderRounds(roundsBoard, rounds, standings) {
  roundsBoard.innerHTML = "";

  rounds.forEach((round, roundIndex) => {
    const col = document.createElement("article");
    col.className = "round-column";
    col.dataset.roundIndex = String(roundIndex);

    const h = document.createElement("h3");
    h.className = "round-title";
    h.textContent = `Round ${roundIndex + 1}`;
    col.appendChild(h);

    const matchesWrap = document.createElement("div");
    matchesWrap.className = "round-matches";

    round.forEach((match, matchIndex) => {
      const key = `${roundIndex}:${matchIndex}`;
      const standing = standings[key] || {};
      const m = document.createElement("div");
      m.className = "match";
      m.dataset.matchIndex = String(matchIndex);

      const top = document.createElement("button");
      top.className = [
        "team-btn",
        "vote-btn",
        match.winner === match.team1 ? "winner" : "",
        standing.my_vote === match.team1 ? "my-vote" : "",
      ]
        .filter(Boolean)
        .join(" ");
      top.textContent = match.team1 || "TBD";
      top.dataset.team = match.team1 || "";
      if (!match.team1 || match.team1 === "BYE") top.disabled = true;

      const bottom = document.createElement("button");
      bottom.className = [
        "team-btn",
        "vote-btn",
        match.winner === match.team2 ? "winner" : "",
        standing.my_vote === match.team2 ? "my-vote" : "",
      ]
        .filter(Boolean)
        .join(" ");
      bottom.textContent = match.team2 || "TBD";
      bottom.dataset.team = match.team2 || "";
      if (!match.team2 || match.team2 === "BYE") bottom.disabled = true;

      const standingEl = document.createElement("p");
      standingEl.className = "standing";
      standingEl.dataset.standingKey = key;
      standingEl.textContent = `${standing.team1_votes || 0} - ${standing.team2_votes || 0}`;

      m.appendChild(top);
      m.appendChild(bottom);
      m.appendChild(standingEl);
      matchesWrap.appendChild(m);
    });

    col.appendChild(matchesWrap);
    roundsBoard.appendChild(col);
  });

  layoutRounds(roundsBoard);
  drawConnectors(roundsBoard);
}

function syncChampion(champion) {
  const championBanner = document.getElementById("champion-banner");
  const championName = document.getElementById("champion-name");
  if (!championBanner || !championName) return;

  if (champion) {
    championBanner.classList.remove("hidden");
    championName.textContent = champion;
  } else {
    championBanner.classList.add("hidden");
    championName.textContent = "";
  }
}

function setupBracketInteractions() {
  const board = document.getElementById("rounds-board");
  if (!board) return;

  const bracketId = board.dataset.bracketId;
  let rounds = JSON.parse(board.dataset.rounds || "[]");
  let standings = JSON.parse(board.dataset.standings || "{}");
  let lastVoteAction = null;

  const resetBtn = document.getElementById("reset-bracket");
  const resetModal = document.getElementById("reset-modal");
  const cancelResetBtn = document.getElementById("cancel-reset");
  const confirmResetBtn = document.getElementById("confirm-reset");

  async function castVote(roundIndex, matchIndex, team) {
    const res = await fetch(`/api/brackets/${bracketId}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round_index: roundIndex, match_index: matchIndex, team }),
    });

    const data = await res.json();
    if (!res.ok) {
      setFeedback(data.error || "Could not submit vote.", "error");
      return;
    }

    rounds = data.rounds;
    standings = data.standings || {};
    renderRounds(board, rounds, standings);
    syncChampion(data.champion);
    setFeedback(`Vote submitted for ${team}.`, "success");
  }

  async function undoLastVote() {
    if (!lastVoteAction) return;
    const { roundIndex, matchIndex, previousVote } = lastVoteAction;
    const undoTeam = previousVote || null;

    const res = await fetch(`/api/brackets/${bracketId}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round_index: roundIndex, match_index: matchIndex, team: undoTeam }),
    });

    const data = await res.json();
    if (!res.ok) {
      setFeedback(data.error || "Could not undo vote.", "error");
      return;
    }

    rounds = data.rounds;
    standings = data.standings || {};
    renderRounds(board, rounds, standings);
    syncChampion(data.champion);
    lastVoteAction = null;
    setFeedback("Last vote undone.", "success");
  }

  board.addEventListener("click", async (event) => {
    const btn = event.target.closest(".vote-btn");
    if (!btn || btn.disabled) return;

    const match = btn.closest(".match");
    const col = btn.closest(".round-column");
    const team = btn.dataset.team;
    if (!team || team === "BYE") return;

    const roundIndex = Number(col.dataset.roundIndex);
    const matchIndex = Number(match.dataset.matchIndex);
    const key = `${roundIndex}:${matchIndex}`;
    const previousVote = standings[key]?.my_vote || null;
    await castVote(roundIndex, matchIndex, team);
    lastVoteAction = { roundIndex, matchIndex, previousVote };
    setFeedbackWithUndo(`Vote submitted for ${team}.`, undoLastVote);
  });

  async function resetBracketVotes() {
    const res = await fetch(`/api/brackets/${bracketId}/reset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    const data = await res.json();
    if (!res.ok) {
      setFeedback(data.error || "Could not reset bracket.", "error");
      return;
    }

    rounds = data.rounds;
    standings = data.standings || {};
    renderRounds(board, rounds, standings);
    syncChampion(data.champion);
    setFeedback("All votes cleared.", "success");
  }

  if (resetBtn && resetModal && cancelResetBtn && confirmResetBtn) {
    resetBtn.addEventListener("click", () => {
      resetModal.showModal();
    });

    cancelResetBtn.addEventListener("click", () => {
      resetModal.close();
    });

    confirmResetBtn.addEventListener("click", async () => {
      resetModal.close();
      await resetBracketVotes();
    });
  }

  renderRounds(board, rounds, standings);
  setupBoardScrollEnhancements(board);
  setupBoardDragPan(board);
  setupBoardZoomControls(board, () => {
    layoutRounds(board);
    drawConnectors(board);
  });
  window.addEventListener("resize", () => {
    layoutRounds(board);
    drawConnectors(board);
  });
}

function setupShareButton() {
  const buttons = Array.from(document.querySelectorAll("#copy-share, .copy-share-btn"));
  if (buttons.length === 0) return;

  buttons.forEach((btn) => {
    if (!btn.dataset.defaultLabel) btn.dataset.defaultLabel = btn.textContent;
  });

  buttons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const bracketId = btn.dataset.bracketId;
      const modeSelect = document.getElementById("share-mode");
      const mode = modeSelect ? modeSelect.value : "filled";

      const res = await fetch(`/api/brackets/${bracketId}/share`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      const data = await res.json();

      if (!res.ok) {
        setFeedback(data.error || "Unable to create share link.", "error");
        return;
      }

      try {
        await navigator.clipboard.writeText(data.share_url);
        btn.textContent = "Link Copied";
        setFeedback("Share link copied.", "success");
        window.setTimeout(() => {
          btn.textContent = btn.dataset.defaultLabel || "Copy Share Link";
        }, 1600);
      } catch (_err) {
        prompt("Copy this share URL:", data.share_url);
      }
    });
  });
}

function setupInviteButton() {
  const inviteBtn = document.getElementById("send-invite");
  const inviteEmail = document.getElementById("invite-email");
  if (!inviteBtn || !inviteEmail) return;

  inviteBtn.addEventListener("click", async () => {
    const email = inviteEmail.value.trim();
    if (!email) {
      setFeedback("Enter an email to invite.", "error");
      return;
    }

    const bracketId = inviteBtn.dataset.bracketId;
    const res = await fetch(`/api/brackets/${bracketId}/invite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json();

    if (!res.ok) {
      setFeedback(data.error || "Could not send invite.", "error");
      return;
    }

    inviteEmail.value = "";
    if (data.email_sent) {
      setFeedback("Invite sent via email.", "success");
    } else {
      setFeedback("Invite created. Email API not configured, link logged in server output.", "info");
    }
  });
}

setupByePreparation();
setupBracketInteractions();
setupShareButton();
setupInviteButton();
