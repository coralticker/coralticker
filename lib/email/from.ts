// Send-only subdomain send.coralticker.com for reputation isolation — digest-
// send reputation never touches an apex mail stream (a future jon@coralticker.com
// or any apex mailbox). From-name is the CoralTicker brand wordmark — a surface
// boundary, so no "Jon" string product-side (the email body "I" is the handshake
// carve-out, not the envelope). The `send.` label is reader-visible in the
// from-address; swapping it to mail./drops. is a DNS-only change.

export const FROM_NAME = 'CoralTicker';
export const FROM_ADDRESS = 'drops@send.coralticker.com';

// Resend's `from` field wants the RFC 5322 "Name <addr>" form.
export const FROM = `${FROM_NAME} <${FROM_ADDRESS}>`;
