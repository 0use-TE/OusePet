const previews = {
  library: { image: 'assets/library.webp', caption: '宠物图库 · 沿着时间线，重看每一个普通又珍贵的日常', alt: '宠物图库实际界面：按日期排列照片，支持物种筛选和时间线跳转' },
  pets: { image: 'assets/pets.webp', caption: '宠物档案 · 按自己的习惯排列每一位小伙伴', alt: '宠物档案实际界面：基米、扣嘚等宠物拥有独立档案与编辑入口' },
  sharing: { image: 'assets/sharing.webp', caption: '回忆分享 · 一份链接，分享一段喜欢的时光', alt: '分享回忆实际界面：设置链接有效期、提取码和原文件下载权限' },
};
const tabs = [...document.querySelectorAll('[data-preview]')];
function selectPreview(tab) {
  const preview = previews[tab.dataset.preview];
  tabs.forEach((item) => { const selected = item === tab; item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1; });
  const image = document.querySelector('#preview-image');
  image.src = preview.image; image.alt = preview.alt;
  document.querySelector('#preview-open').dataset.image = preview.image;
  document.querySelector('#preview-open').dataset.caption = preview.caption;
  document.querySelector('#preview-caption').textContent = preview.caption;
  document.querySelector('#preview-panel').setAttribute('aria-labelledby', tab.id);
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectPreview(tab));
  tab.addEventListener('keydown', (event) => {
    let target;
    if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
    if (event.key === 'ArrowLeft') target = tabs[(index - 1 + tabs.length) % tabs.length];
    if (event.key === 'Home') target = tabs[0];
    if (event.key === 'End') target = tabs[tabs.length - 1];
    if (target) { event.preventDefault(); target.focus(); selectPreview(target); }
  });
});
const viewer = document.querySelector('#image-viewer');
document.querySelectorAll('.screenshot-button').forEach((button) => button.addEventListener('click', () => {
  const image = document.querySelector('#viewer-image');
  image.src = button.dataset.image; image.alt = button.dataset.caption;
  document.querySelector('#viewer-caption').textContent = button.dataset.caption;
  viewer.showModal();
}));
document.querySelector('#close-viewer').addEventListener('click', () => viewer.close());
viewer.addEventListener('click', (event) => { if (event.target === viewer) { const box = viewer.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) viewer.close(); } });
document.querySelector('#copy-clone').addEventListener('click', async () => {
  const command = 'git clone https://github.com/0use-TE/OusePet.git';
  const status = document.querySelector('#copy-status');
  try { await navigator.clipboard.writeText(command); status.textContent = '克隆命令已复制'; }
  catch { status.textContent = command; }
});
