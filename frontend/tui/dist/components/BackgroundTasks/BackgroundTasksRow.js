import { c as _c } from "react/compiler-runtime";
import { jsx as _jsx } from "react/jsx-runtime";
import { useStore } from '@nanostores/react';
import { memo } from 'react';
import { $uiState } from '../../app/uiStore.js';
import { strings } from '../../content/strings.js';
import { ChatLoadingRow } from '../Thinking/components/ChatLoadingRow/index.js';
/** Spinner no transcript enquanto há tarefas `/background` (`/btw`) pendentes. */
export const BackgroundTasksRow = memo(function BackgroundTasksRow() {
  const $ = _c(3);
  const {
    bgTasks,
    theme
  } = useStore($uiState);
  const n = bgTasks.size;
  if (n <= 0) {
    return null;
  }
  let t0;
  if ($[0] !== n || $[1] !== theme) {
    const label = n === 1 ? strings.slash.backgroundRunning : strings.slash.backgroundRunningMany(n);
    t0 = _jsx(ChatLoadingRow, {
      label,
      t: theme
    });
    $[0] = n;
    $[1] = theme;
    $[2] = t0;
  } else {
    t0 = $[2];
  }
  return t0;
});