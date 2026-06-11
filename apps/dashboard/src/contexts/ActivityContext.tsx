import { createContext, useContext } from 'react';

interface ActivityCtx {
  isOpen: boolean;
  open: () => void;
  close: () => void;
}

export const ActivityContext = createContext<ActivityCtx>({
  isOpen: false,
  open: () => {},
  close: () => {},
});

export const useActivity = () => useContext(ActivityContext);
