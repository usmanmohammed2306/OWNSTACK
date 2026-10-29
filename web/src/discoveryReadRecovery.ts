/** A lost connection does not prove saved work disappeared. Authority denial does. */
export function forgetDiscoveryAfter(error:unknown):boolean {
 if(!error||typeof error!=='object'||!('status' in error))return false;
 return [401,403,404].includes((error as {status:number}).status);
}
