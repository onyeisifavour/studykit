export interface StudyKitApi {
  getApiUrl(): Promise<string>;
  getUser(): Promise<{ name: string }>;
  browseFolder(): Promise<string | null>;
}

declare global {
  interface Window {
    studykit: StudyKitApi;
  }
}

export {};
