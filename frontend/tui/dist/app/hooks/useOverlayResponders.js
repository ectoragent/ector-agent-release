import { c as _c } from "react/compiler-runtime";
import { useCallback } from 'react';
import { STATUS } from '../../content/uiStatus.js';
import { WISER_USER_CANCELLED } from '../../content/wiserMessages.js';
import { buildToolTrailLine, toolTrailLabel } from '../../lib/text.js';
import { getOverlayState, patchOverlayState } from '../overlayStore.js';
import { turnController } from '../turn/index.js';
import { patchTurnState } from '../turnStore.js';
import { patchUiState } from '../uiStore.js';
export function useOverlayResponders(opts) {
  const $ = _c(24);
  const {
    appendMessage,
    overlaySecret,
    overlaySudo,
    overlayWiser,
    rpc,
    sessionId,
    slashRef,
    sys
  } = opts;
  let t0;
  if ($[0] !== rpc) {
    t0 = (method, params, done) => rpc(method, params).then(r => r && done());
    $[0] = rpc;
    $[1] = t0;
  } else {
    t0 = $[1];
  }
  const respondWith = t0;
  let t1;
  if ($[2] !== respondWith || $[3] !== sessionId) {
    t1 = choice => respondWith("approval.respond", {
      choice,
      session_id: sessionId
    }, () => {
      patchOverlayState({
        approval: null
      });
      patchTurnState({
        outcome: choice === "deny" ? "denied" : `approved (${choice})`
      });
      patchUiState({
        status: STATUS.running
      });
    });
    $[2] = respondWith;
    $[3] = sessionId;
    $[4] = t1;
  } else {
    t1 = $[4];
  }
  const answerApproval = t1;
  let t2;
  if ($[5] !== overlaySudo || $[6] !== respondWith) {
    t2 = pw => {
      if (!overlaySudo) {
        return;
      }
      return respondWith("sudo.respond", {
        password: pw,
        request_id: overlaySudo.requestId
      }, _temp);
    };
    $[5] = overlaySudo;
    $[6] = respondWith;
    $[7] = t2;
  } else {
    t2 = $[7];
  }
  const answerSudo = t2;
  let t3;
  if ($[8] !== overlaySecret || $[9] !== respondWith) {
    t3 = value => {
      if (!overlaySecret) {
        return;
      }
      return respondWith("secret.respond", {
        request_id: overlaySecret.requestId,
        value
      }, _temp2);
    };
    $[8] = overlaySecret;
    $[9] = respondWith;
    $[10] = t3;
  } else {
    t3 = $[10];
  }
  const answerSecret = t3;
  let t4;
  if ($[11] !== appendMessage || $[12] !== overlayWiser || $[13] !== rpc || $[14] !== sys) {
    t4 = answer => {
      const pending = getOverlayState().wiser ?? overlayWiser;
      if (!pending) {
        return;
      }
      const {
        question,
        requestId
      } = pending;
      patchOverlayState({
        wiser: null
      });
      turnController.removeTrailGroup("wiser", question);
      const resolved = answer && answer !== WISER_USER_CANCELLED ? answer : WISER_USER_CANCELLED;
      const cancelled = resolved === WISER_USER_CANCELLED;
      rpc("wiser.respond", {
        answer: resolved,
        request_id: requestId
      }).then(r_0 => {
        if (!r_0) {
          return;
        }
        if (cancelled) {
          sys("prompt cancelled");
        } else {
          turnController.persistedToolLabels.add(toolTrailLabel("wiser"));
          appendMessage({
            kind: "trail",
            role: "system",
            text: "",
            tools: [buildToolTrailLine("wiser", question)]
          });
          appendMessage({
            role: "user",
            text: resolved
          });
          patchUiState({
            status: STATUS.running
          });
        }
      });
    };
    $[11] = appendMessage;
    $[12] = overlayWiser;
    $[13] = rpc;
    $[14] = sys;
    $[15] = t4;
  } else {
    t4 = $[15];
  }
  const answerWiser = t4;
  let t5;
  if ($[16] !== slashRef) {
    t5 = value_0 => {
      patchOverlayState({
        modelPicker: false
      });
      slashRef.current(`/provider ${value_0} --global`);
    };
    $[16] = slashRef;
    $[17] = t5;
  } else {
    t5 = $[17];
  }
  const onModelSelect = t5;
  let t6;
  if ($[18] !== answerApproval || $[19] !== answerSecret || $[20] !== answerSudo || $[21] !== answerWiser || $[22] !== onModelSelect) {
    t6 = {
      answerApproval,
      answerSecret,
      answerSudo,
      answerWiser,
      onModelSelect
    };
    $[18] = answerApproval;
    $[19] = answerSecret;
    $[20] = answerSudo;
    $[21] = answerWiser;
    $[22] = onModelSelect;
    $[23] = t6;
  } else {
    t6 = $[23];
  }
  return t6;
}
function _temp2() {
  patchOverlayState({
    secret: null
  });
  patchUiState({
    status: STATUS.running
  });
}
function _temp() {
  patchOverlayState({
    sudo: null
  });
  patchUiState({
    status: STATUS.running
  });
}