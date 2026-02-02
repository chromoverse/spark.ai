import { createRoot } from "react-dom/client";
import "./index.css";
import "./App.css";
import App from "./App.tsx";
import { Provider } from "react-redux";
import { store } from "./store/store.ts";
import { SocketProvider } from "./context/socketContextProvider.tsx";
import { SparkTTSProvider } from "./context/sparkTTSContext.tsx";

const user  = {
  _id: "guest",
};

createRoot(document.getElementById("root")!).render(
  <Provider store={store}>
    <SocketProvider value={user}>
      <SparkTTSProvider>
        <App />
      </SparkTTSProvider>
    </SocketProvider>
  </Provider>
);