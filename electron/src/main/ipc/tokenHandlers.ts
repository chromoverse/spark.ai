import { ipcMainHandle } from "../utils/ipcUtils.js";

export function registerTokenHandlers() {
  ipcMainHandle("saveToken", async (_event, { ACCOUNT_NAME, token }) => {
    const { saveToken } = await import("../services/TokenManager.js");
    return await saveToken(ACCOUNT_NAME, token);
  });

  ipcMainHandle("getToken", async (_event, { ACCOUNT_NAME }) => {
    const { getToken } = await import("../services/TokenManager.js");
    return await getToken(ACCOUNT_NAME);
  });

  ipcMainHandle("deleteToken", async (_event, { ACCOUNT_NAME }) => {
    const { deleteToken } = await import("../services/TokenManager.js");
    return await deleteToken(ACCOUNT_NAME);
  });
}
