import { describe, expect, it } from 'vitest';
import { apiUrl } from './apiUrl';

// apiUrl() is the seam every cross-origin deploy depends on. If this drifts,
// CORS breaks across 24 services silently. Worth a tiny regression test.
describe('apiUrl', () => {
  it('leaves absolute URLs untouched', () => {
    expect(apiUrl('https://api.example.com/foo')).toBe('https://api.example.com/foo');
    expect(apiUrl('http://localhost:8080/bar')).toBe('http://localhost:8080/bar');
  });

  it('prepends a leading slash for bare paths', () => {
    expect(apiUrl('api/foo')).toBe('/api/foo');
  });

  it('preserves leading slash if present', () => {
    expect(apiUrl('/api/foo?x=1')).toBe('/api/foo?x=1');
  });

  it('returns the base when given an empty path', () => {
    // Empty path defaults to '/' so fetch() gets something valid.
    expect(apiUrl('')).toBe('/');
  });
});
