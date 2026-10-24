const status = document.getElementById('status');
const query = location.search.slice(1);
history.replaceState(null, '', '/oauth/callback');

async function finish() {
  const response = await fetch('/api/oauth/finish', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  if (typeof result.location !== 'string' || !result.location.startsWith('/') || result.location.startsWith('//')) {
    throw new Error('認証後の移動先が正しくありません');
  }
  location.replace(result.location);
}

finish().catch(error => { status.textContent = error.message; });
