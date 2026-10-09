export type AuthResponse = {
  success: boolean;
  message: string;
  data: unknown;
  access_token: string;
  refresh_token: string;
};

export type IVerifyOTP = {
  otp : string,
  email : string
}
