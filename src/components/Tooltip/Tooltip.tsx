import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import styles from './Tooltip.module.css';

interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delayMs?: number;
  disabled?: boolean;
  shortcut?: string;
  maxWidth?: number;
}

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  children,
  position = 'top',
  delayMs = 140,
  disabled = false,
  shortcut,
  maxWidth,
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const timeoutRef = useRef<number | null>(null);

  const clearPendingTooltip = () => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  const openTooltip = () => {
    if (disabled) {
      return;
    }

    clearPendingTooltip();
    timeoutRef.current = window.setTimeout(() => {
      setIsVisible(true);
    }, delayMs);
  };

  const closeTooltip = () => {
    clearPendingTooltip();
    setIsVisible(false);
  };

  useEffect(() => {
    return () => {
      clearPendingTooltip();
    };
  }, []);

  return (
    <span
      className={styles.container}
      onMouseEnter={openTooltip}
      onMouseLeave={closeTooltip}
      onFocusCapture={openTooltip}
      onBlurCapture={closeTooltip}
    >
      {children}
      <AnimatePresence>
        {isVisible && !disabled && (
          <motion.div
            initial={{ opacity: 0, y: position === 'top' ? 6 : position === 'bottom' ? -6 : 0, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: position === 'top' ? 6 : position === 'bottom' ? -6 : 0, scale: 0.98 }}
            transition={{ duration: 0.14, ease: 'easeOut' }}
            className={`${styles.tooltip} ${styles[position]}`}
            role="tooltip"
            style={maxWidth ? { maxWidth: `${maxWidth}px` } : undefined}
          >
            <span className={styles.content}>{content}</span>
            {shortcut ? <span className={styles.shortcut}>{shortcut}</span> : null}
          </motion.div>
        )}
      </AnimatePresence>
    </span>
  );
};
