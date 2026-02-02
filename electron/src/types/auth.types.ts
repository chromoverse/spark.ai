export type AuthResponse = {
  success: boolean;
  message: string;
  data: any;
  access_token: string;
  refresh_token: string;
};

export type IVerifyOTP = {
  otp : string,
  email : string
}
