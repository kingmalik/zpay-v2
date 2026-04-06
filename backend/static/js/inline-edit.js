// ---------- helpers ----------
function toNumber(val) {
  const n = parseFloat(val);
  return Number.isFinite(n) ? n : 0;
}

function formatMoney(n) {
  return n.toFixed(2);
}

function recalcRow(rideId) {
  const rateInput = document.querySelector(`#rate-${rideId}`);
  const dedInput  = document.querySelector(`#ded-${rideId}`);
  const grossEl   = document.querySelector(`.gross-value[data-ride-id="${rideId}"]`);
  const netEl     = document.querySelector(`.net-value[data-ride-id="${rideId}"]`);

  const rate = rateInput ? toNumber(rateInput.value) : 0;
  const ded  = dedInput ? toNumber(dedInput.value) : 0;

  const gross = rate;        // business rule: gross = rate
  const net = gross - ded;   // net = gross - deduction

  if (grossEl) grossEl.textContent = formatMoney(gross);
  if (netEl) netEl.textContent = formatMoney(net);
}

// ---------- inline edit (label -> input) ----------
function startEdit(td) {
  td.classList.add("is-editing");
  const input = td.querySelector(".inline-input");
  if (!input) return;
  input.dataset.original = input.value;
  input.focus();
  input.select();
}

function stopEdit(td) {
  td.classList.remove("is-editing");
}

// Click on label => show input
document.addEventListener("click", (e) => {
  const label = e.target.closest(".inline-label");
  if (!label) return;

  const td = label.closest("td.editable");
  if (!td) return;

  startEdit(td);
});

// Enter saves (just updates the label text); Escape cancels
document.addEventListener("keydown", (e) => {
  const input = e.target.closest(".inline-input");
  if (!input) return;

  const td = input.closest("td.editable");
  if (!td) return;

  if (e.key === "Enter") {
    e.preventDefault();
    // update label text to match input
    const label = td.querySelector(".inline-label");
    if (label) label.textContent = input.value;

    // live recalc when leaving field
    const rideId = input.dataset.rideId;
    if (rideId) recalcRow(rideId);

    stopEdit(td);
  }

  if (e.key === "Escape") {
    e.preventDefault();
    input.value = input.dataset.original ?? input.value;
    stopEdit(td);
  }
});

// Blur => update label text and recalc
document.addEventListener("focusout", (e) => {
  const input = e.target.closest(".inline-input");
  if (!input) return;

  const td = input.closest("td.editable");
  if (!td) return;

  const label = td.querySelector(".inline-label");
  if (label) label.textContent = input.value;

  const rideId = input.dataset.rideId;
  if (rideId) recalcRow(rideId);

  stopEdit(td);
});

// ---------- live calc while typing ----------
document.addEventListener("input", (e) => {
  const input = e.target.closest(".inline-input");
  if (!input) return;

  const rideId = input.dataset.rideId;
  if (!rideId) return;

  recalcRow(rideId);
});
