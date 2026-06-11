import { useState, useEffect } from 'react';

interface CounterProps {
  value: number;
  prefix?: string | undefined;
  suffix?: string | undefined;
  decimals?: number | undefined;
}

export function Counter({ value, prefix = "", suffix = "", decimals = 0 }: CounterProps) {
  const [displayValue, setDisplayValue] = useState(0);
  
  useEffect(() => {
    const start = 0;
    const end = value;
    const duration = 1500;
    const startTime = performance.now();
    
    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const ease = 1 - (1 - progress) ** 4; // easeOutQuart
      
      setDisplayValue(start + (end - start) * ease);
      
      if (progress < 1) {
        requestAnimationFrame(animate);
      }
    };
    
    requestAnimationFrame(animate);
  }, [value]);

  return <span>{prefix}{displayValue.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</span>;
}
