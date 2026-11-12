(function(){
const paths = {
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  "arrow-left": '<path d="M19 12H5m5-5-5 5 5 5"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/>',
  mic: '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
  spark:
    '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/><path d="M20 2v4m-2-2h4"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  book: '<path d="M3 4h7l2 2 2-2h7v15h-7l-2 2-2-2H3V4Z"/><path d="M12 6v15M6 8h3m6 0h3M6 12h3m6 0h3"/>',
  sliders:
    '<path d="M4 5h7m6 0h3M4 12h2m6 0h8M4 19h10m6 0h0"/><circle cx="14" cy="5" r="3"/><circle cx="9" cy="12" r="3"/><circle cx="17" cy="19" r="3"/>',
  voice: '<path d="M3 10v4m4-7v10m5-14v18m5-15v12m4-8v4"/>',
  wallet:
    '<rect x="3" y="5" width="18" height="15" rx="2"/><path d="M18 5V2H5a2 2 0 0 0-2 2m13 7h5v5h-5v-5Z"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18Z"/>',
  phone:
    '<path d="M8 3H4a1 1 0 0 0-1 1c0 9 8 17 17 17a1 1 0 0 0 1-1v-4l-5-2-2 3a16 16 0 0 1-7-7l3-2-2-5Z"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  layers: '<path d="m3 8 9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 18l9 5 9-5"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 1 1 4 3c-1 .3-1 1-1 2m0 3h.01"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  play: '<path d="m8 4 13 8-13 8V4Z"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  edit: '<path d="m14 5 5 5M4 20l1-6L16 3l5 5L10 19l-6 1Z"/>',
  link: '<path d="m9 15 6-6m-5-3 2-2a5 5 0 0 1 8 8l-2 2m-4 4-2 2a5 5 0 0 1-8-8l2-2"/>',
  send: '<path d="m3 3 18 9-18 9 4-9-4-9Zm4 9h14"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
};

window.FocusIcons={icon:(name)=>`<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name]||paths.spark}</svg>`,fill:()=>document.querySelectorAll('[data-ui-icon]').forEach(el=>{el.innerHTML=FocusIcons.icon(el.dataset.uiIcon);})};
window.addEventListener('DOMContentLoaded',()=>FocusIcons.fill());
})();
