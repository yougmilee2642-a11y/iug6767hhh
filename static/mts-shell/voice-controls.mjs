export function controlsLocked(state, controller) {
  return !controller?.id || !controller.privacyReady || controller.completed || controller.closed ||
    ['connecting', 'transcribing', 'thinking', 'speaking', 'ended', 'completed'].includes(state);
}
