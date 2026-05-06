import React from 'react';
import { motion, type HTMLMotionProps } from 'framer-motion';
import styles from './Button.module.css';

interface ButtonProps extends Omit<HTMLMotionProps<"button">, 'ref'> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  icon?: React.ReactNode;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({
    children,
    variant = 'primary',
    size = 'md',
    icon,
    loading,
    className = '',
    disabled,
    ...props
  }, ref) => {
    const button = (
      <motion.button
        ref={ref}
        whileHover={disabled || loading ? {} : { scale: 1.02 }}
        whileTap={disabled || loading ? {} : { scale: 0.98 }}
        className={`${styles.button} ${styles[variant]} ${styles[size]} ${className}`}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? (
          <div className={styles.spinner} />
        ) : icon ? (
          <span className={styles.iconWrapper}>{icon}</span>
        ) : null}
        {children as React.ReactNode}
      </motion.button>
    );

    return button;
  }
);

Button.displayName = 'Button';
