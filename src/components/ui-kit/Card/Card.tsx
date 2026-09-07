import React from 'react';
import { motion, type HTMLMotionProps } from 'framer-motion';
import styles from './Card.module.css';

interface CardProps extends HTMLMotionProps<"div"> {
  children: React.ReactNode;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  variant?: 'glass' | 'solid';
}

export const Card: React.FC<CardProps> = ({ children, padding = 'md', variant = 'glass', className = '', ...props }) => {
  return (
    <motion.div 
      className={`${styles.card} ${styles[padding]} ${styles[variant]} ${className}`}
      {...props}
    >
      {children}
    </motion.div>
  );
};
