// frontend/src/api/client.ts
import axios from 'axios';

const client = axios.create({
  baseURL: '/api',
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('nous_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    // FastAPI reports failures in `detail`, whose shape depends on the error:
    // a handler raising HTTPException gives a string, while a 422 validation
    // failure gives a list of {loc, msg, type} dicts. Callers render
    // error.message straight into the DOM, and an array child throws there, so
    // every shape is collapsed to a string here.
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') {
      error.message = detail;
    } else if (Array.isArray(detail)) {
      // Every entry is kept and prefixed with the field it names — the last
      // usable element of `loc`, since the head is just "body"/"query". A
      // malformed batch fails on several lines at once and naming only the
      // first hides the rest.
      const parts = detail.map((d) => {
        const msg = String(d?.msg ?? 'Invalid value');
        const loc = Array.isArray(d?.loc) ? d.loc : [];
        const field = [...loc].reverse().find((p) => typeof p === 'string' && p && p !== 'body');
        return field ? `${field}: ${msg}` : msg;
      });
      error.message = parts.join('; ').slice(0, 200) || 'Invalid request';
    } else if (error.response) {
      error.message = `Request failed (${error.response.status})`;
    }

    if (error.response?.status === 401) {
      localStorage.removeItem('nous_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default client;
