const button = document.querySelector('#copy-source');
const status = document.querySelector('#copy-status');
const address = document.querySelector('#source-address');

button.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(address.textContent);
    status.textContent = 'Repository URL copied.';
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(address);
    selection.removeAllRanges();
    selection.addRange(range);
    status.textContent = 'Select and copy the repository URL above.';
  }
});
