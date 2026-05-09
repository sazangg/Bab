let accessToken: string | null = null;

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(nextAccessToken: string | null) {
  accessToken = nextAccessToken;
}
