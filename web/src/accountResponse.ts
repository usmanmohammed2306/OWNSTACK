import { boundedResponse, type BoundedResponse } from './responseDeadline.ts';

/** Authentication includes password verification and several durable DB steps.
 * Allow a bounded longer wait than ordinary reads, without resending a write or
 * claiming that a locally canceled request was canceled by the server.
 */
export function accountResponse<T>(request: (signal: AbortSignal) => Promise<T>): BoundedResponse<T> {
  return boundedResponse(request, 30_000);
}
