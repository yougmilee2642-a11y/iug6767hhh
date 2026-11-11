// One real owner workspace. Old concept URLs stay usable without publishing mocks.
export function cabinetTarget(hash) {
  const parts=String(hash).replace(/^#/,'').split('/');
  if(parts[0]!=='cabinet')return null;
  const routes={overview:'overview',agents:'assistant',agent:'assistant',knowledge:'knowledge',history:'applications',settings:'channels'};
  return '/#'+(routes[parts[1]]||'overview');
}
