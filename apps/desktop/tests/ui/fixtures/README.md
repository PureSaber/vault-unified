# Generated QR fixture

`totp-rfc-test.png` encodes an `otpauth://totp/RFC` URI with the public SHA-1 key
`12345678901234567890` from RFC 6238 Appendix B, Base32 encoded, and issuer
`Generated`, with a two-second period to exercise live rollover. It uses public
test data, not a user authenticator or account. Standard 30-second RFC vectors
are verified separately by the Python tests.

Generated once with Python qrcode 8.2; no QR generator is needed at test runtime.
The renderer journey uses the actual bundled jsQR decoder on this local PNG.
