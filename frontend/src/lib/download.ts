// frontend/src/lib/download.ts

/**
 * Hand a blob to the browser as a file download.
 *
 * The object URL is revoked as soon as the synthetic click has been dispatched;
 * the browser has already taken its own reference to the blob by then, so
 * holding the URL open would only leak it.
 */
export function downloadBlob(data: BlobPart, filename: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([data], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
