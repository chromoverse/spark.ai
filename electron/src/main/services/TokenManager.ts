import keytar from "keytar";

const SERVICE_NAME = "tokenManagementService";
// const ACCOUNT_NAME = "user-token";

export async function saveToken(ACCOUNT_NAME: string, token: string): Promise<void> {
  await keytar.setPassword(SERVICE_NAME, ACCOUNT_NAME, token);
}

export async function getToken(ACCOUNT_NAME: string): Promise<string | null> {
  return await keytar.getPassword(SERVICE_NAME, ACCOUNT_NAME);
}

export async function deleteToken(ACCOUNT_NAME: string): Promise<void> {
  await keytar.deletePassword(SERVICE_NAME, ACCOUNT_NAME);
}
