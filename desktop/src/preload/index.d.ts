export interface StudyKitApi {
  getApiUrl(): Promise<string>;
  getUser(): Promise<{ name: string }>;
}

declare global {
  interface Window {
    studykit: StudyKitApi;
  }
}

export {};
