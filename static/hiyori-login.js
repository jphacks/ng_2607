(() => {
  const form = document.querySelector('#login-form');
  const error = document.querySelector('#login-error');
  const showError = message => {error.textContent = message; error.hidden = false;};
  fetch('/api/auth', {credentials: 'same-origin'})
    .then(response => response.json())
    .then(data => {if (data.did) location.replace('/');})
    .catch(() => {});
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const handle = document.querySelector('#handle').value.trim().replace(/^@/, '');
    if (!/^[a-zA-Z0-9.-]{3,253}$/.test(handle)) {
      showError('有効なBlueskyハンドルを入力してください。');
      return;
    }
    const button = form.querySelector('button');
    button.disabled = true;
    error.hidden = true;
    try {
      const response = await fetch('/api/oauth/start', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({role: 'player', handle}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '認証を開始できませんでした。');
      location.assign(data.url);
    } catch (cause) {
      showError(cause.message);
      button.disabled = false;
    }
  });
})();
