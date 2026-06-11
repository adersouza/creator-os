/**
 * Form Validation Utility
 * Provides validation functions for common form fields
 * Returns error messages for invalid inputs, null for valid
 */

export interface ValidationResult {
  isValid: boolean;
  error: string | null;
}

/**
 * Validate email address
 */
export const validateEmail = (email: string): ValidationResult => {
  if (!email || email.trim() === '') {
    return { isValid: false, error: 'Email is required' };
  }

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRegex.test(email)) {
    return { isValid: false, error: 'Please enter a valid email address' };
  }

  return { isValid: true, error: null };
};

/**
 * Validate post content
 */
export const validatePostContent = (content: string, maxLength: number = 500): ValidationResult => {
  if (!content || content.trim() === '') {
    return { isValid: false, error: 'Post content cannot be empty' };
  }

  if (content.length > maxLength) {
    return { isValid: false, error: `Content must be ${maxLength} characters or less` };
  }

  return { isValid: true, error: null };
};

/**
 * Validate scheduled date
 */
export const validateScheduledDate = (date: Date | string): ValidationResult => {
  if (!date) {
    return { isValid: false, error: 'Please select a date and time' };
  }

  const scheduledDate = typeof date === 'string' ? new Date(date) : date;
  const now = new Date();

  if (Number.isNaN(scheduledDate.getTime())) {
    return { isValid: false, error: 'Invalid date format' };
  }

  if (scheduledDate <= now) {
    return { isValid: false, error: 'Scheduled time must be in the future' };
  }

  // Require at least 2 minutes buffer so the cron has time to pick it up
  const twoMinutesFromNow = new Date(now.getTime() + 2 * 60 * 1000);
  if (scheduledDate < twoMinutesFromNow) {
    return { isValid: false, error: 'Scheduled time must be at least 2 minutes from now' };
  }

  // Cap at 6 months — API tokens may expire beyond this window
  const sixMonthsFromNow = new Date();
  sixMonthsFromNow.setMonth(sixMonthsFromNow.getMonth() + 6);

  if (scheduledDate > sixMonthsFromNow) {
    return { isValid: false, error: 'Scheduled time cannot be more than 6 months in the future (API tokens may expire)' };
  }

  return { isValid: true, error: null };
};

/**
 * Validate URL
 */
export const validateUrl = (url: string, required: boolean = false): ValidationResult => {
  if (!url || url.trim() === '') {
    if (required) {
      return { isValid: false, error: 'URL is required' };
    }
    return { isValid: true, error: null };
  }

  try {
    new URL(url);
    return { isValid: true, error: null };
  } catch {
    return { isValid: false, error: 'Please enter a valid URL' };
  }
};

/**
 * Validate API key format
 */
export const validateApiKey = (apiKey: string, minLength: number = 20): ValidationResult => {
  if (!apiKey || apiKey.trim() === '') {
    return { isValid: false, error: 'API key is required' };
  }

  if (apiKey.length < minLength) {
    return { isValid: false, error: `API key must be at least ${minLength} characters` };
  }

  return { isValid: true, error: null };
};

/**
 * Validate number within range
 */
export const validateNumber = (
  value: number | string,
  min?: number,
  max?: number
): ValidationResult => {
  const num = typeof value === 'string' ? parseFloat(value) : value;

  if (Number.isNaN(num)) {
    return { isValid: false, error: 'Please enter a valid number' };
  }

  if (min !== undefined && num < min) {
    return { isValid: false, error: `Value must be at least ${min}` };
  }

  if (max !== undefined && num > max) {
    return { isValid: false, error: `Value must be at most ${max}` };
  }

  return { isValid: true, error: null };
};

/**
 * Validate required field
 */
// biome-ignore lint/suspicious/noExplicitAny: generic validator accepts any form value type
export const validateRequired = (value: any, fieldName: string = 'This field'): ValidationResult => {
  if (value === null || value === undefined) {
    return { isValid: false, error: `${fieldName} is required` };
  }

  if (typeof value === 'string' && value.trim() === '') {
    return { isValid: false, error: `${fieldName} is required` };
  }

  if (Array.isArray(value) && value.length === 0) {
    return { isValid: false, error: `${fieldName} is required` };
  }

  return { isValid: true, error: null };
};

/**
 * Validate password strength
 */
export const validatePassword = (password: string): ValidationResult => {
  if (!password || password.trim() === '') {
    return { isValid: false, error: 'Password is required' };
  }

  if (password.length < 8) {
    return { isValid: false, error: 'Password must be at least 8 characters long' };
  }

  const hasUpperCase = /[A-Z]/.test(password);
  const hasLowerCase = /[a-z]/.test(password);
  const hasNumber = /\d/.test(password);

  if (!hasUpperCase || !hasLowerCase || !hasNumber) {
    return {
      isValid: false,
      error: 'Password must contain uppercase, lowercase, and numbers',
    };
  }

  return { isValid: true, error: null };
};

/**
 * Validate image file
 */
export const validateImageFile = (file: File | null, maxSizeMB: number = 5): ValidationResult => {
  if (!file) {
    return { isValid: false, error: 'Please select an image' };
  }

  const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];
  if (!allowedTypes.includes(file.type)) {
    return { isValid: false, error: 'File must be an image (JPEG, PNG, GIF, or WebP)' };
  }

  const maxSizeBytes = maxSizeMB * 1024 * 1024;
  if (file.size > maxSizeBytes) {
    return { isValid: false, error: `Image must be smaller than ${maxSizeMB}MB` };
  }

  return { isValid: true, error: null };
};

/**
 * Validate goal value (positive number)
 */
export const validateGoal = (value: number | string): ValidationResult => {
  const num = typeof value === 'string' ? parseFloat(value) : value;

  if (Number.isNaN(num)) {
    return { isValid: false, error: 'Please enter a valid goal' };
  }

  if (num <= 0) {
    return { isValid: false, error: 'Goal must be a positive number' };
  }

  if (num > 1000000) {
    return { isValid: false, error: 'Goal is unrealistically high' };
  }

  return { isValid: true, error: null };
};

/**
 * Compose multiple validators
 */
export const composeValidators = (
  // biome-ignore lint/suspicious/noExplicitAny: generic validator composer accepts any form value type
  ...validators: ((value: any) => ValidationResult)[]
// biome-ignore lint/suspicious/noExplicitAny: generic validator composer accepts any form value type
): ((value: any) => ValidationResult) => {
  // biome-ignore lint/suspicious/noExplicitAny: generic validator composer accepts any form value type
  return (value: any) => {
    for (const validator of validators) {
      const result = validator(value);
      if (!result.isValid) {
        return result;
      }
    }
    return { isValid: true, error: null };
  };
};

export default {
  email: validateEmail,
  postContent: validatePostContent,
  scheduledDate: validateScheduledDate,
  url: validateUrl,
  apiKey: validateApiKey,
  number: validateNumber,
  required: validateRequired,
  password: validatePassword,
  imageFile: validateImageFile,
  goal: validateGoal,
  compose: composeValidators,
};
