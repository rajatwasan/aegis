"""Single-file HTML approval page. No framework; plain fetch calls."""

APPROVAL_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Aegis — pending approvals</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; }
  h1 { font-size: 1.4rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ccc; padding: .5rem .7rem; text-align: left; font-size: .9rem; }
  th { background: #f5f5f5; }
  button { padding: .3rem .8rem; margin-right: .4rem; cursor: pointer; }
  .approve { background: #d8f5d8; }
  .reject { background: #f5d8d8; }
  #empty { color: #777; margin-top: 1rem; }
</style>
</head>
<body>
<h1>Aegis — pending approvals</h1>
<p>Approver: <input id="approver" value="ops-1"> Comment: <input id="comment" size="40"></p>
<table id="tbl" hidden>
  <thead><tr>
    <th>Decision</th><th>Op</th><th>From</th><th>To</th><th>Class</th><th>Amount</th>
    <th>Approvals</th><th>Actions</th>
  </tr></thead>
  <tbody id="rows"></tbody>
</table>
<p id="empty">Nothing pending.</p>
<script>
async function refresh() {
  const res = await fetch('/proposals?status=pending');
  const items = await res.json();
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  document.getElementById('tbl').hidden = items.length === 0;
  document.getElementById('empty').hidden = items.length !== 0;
  for (const p of items) {
    const tr = document.createElement('tr');
    const prop = p.proposal;
    tr.innerHTML =
      `<td>${p.decision_id.slice(0, 8)}…</td><td>${prop.operation}</td>` +
      `<td>${prop.from}</td><td>${prop.to}</td><td>${prop.asset_class ?? 0}</td>` +
      `<td>${prop.amount}</td><td>${p.approvals.length}</td><td></td>`;
    const cell = tr.lastElementChild;
    for (const action of ['approve', 'reject']) {
      const btn = document.createElement('button');
      btn.textContent = action;
      btn.className = action;
      btn.onclick = () => act(p.decision_id, action);
      cell.appendChild(btn);
    }
    rows.appendChild(tr);
  }
}
async function act(id, action) {
  await fetch(`/proposals/${id}/${action}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      approver: document.getElementById('approver').value,
      comment: document.getElementById('comment').value,
    }),
  });
  refresh();
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
