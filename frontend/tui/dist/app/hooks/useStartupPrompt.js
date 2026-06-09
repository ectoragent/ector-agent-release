import { useEffect, useRef } from 'react';
import { useStore } from '@nanostores/react';
import { STARTUP_INITIAL_IMAGE, STARTUP_INITIAL_PROMPT, STARTUP_RESUME_ID } from '../../config/env.js';
import { isComposerReady } from '../../content/uiStatus.js';
import { rpcErrorMessage } from '../../lib/rpc.js';
import { $uiState } from '../uiStore.js';
/** Auto-submit the CLI `-q` / `--image` startup payload once the session is ready. */
export function useStartupPrompt(gw, submitRef, sys) {
  const ui = useStore($uiState);
  const fired = useRef(false);
  useEffect(() => {
    if (fired.current || STARTUP_RESUME_ID) {
      return;
    }
    const prompt = STARTUP_INITIAL_PROMPT;
    const imagePath = STARTUP_INITIAL_IMAGE;
    if (!prompt && !imagePath) {
      return;
    }
    if (!isComposerReady(ui)) {
      return;
    }
    fired.current = true;
    const sid = ui.sid;
    void (async () => {
      let submitText = prompt;
      if (imagePath) {
        try {
          const r = await gw.request('image.attach', {
            path: imagePath,
            session_id: sid
          });
          if (r?.name) {
            submitText = (r.remainder?.trim() || prompt || '').trim() || prompt;
          }
        } catch (e) {
          sys(`startup image attach failed: ${rpcErrorMessage(e)}`);
          return;
        }
      }
      if (submitText || imagePath) {
        submitRef.current(submitText);
      }
    })();
  }, [gw, submitRef, sys, ui.busy, ui.sid, ui.status]);
}