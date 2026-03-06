import { apiGet } from "@/common/services/api";

export interface ClassOption {
  id: string;
  name: string;
  section?: string;
}

export const financeClassService = {
  getClasses: async (): Promise<ClassOption[]> => {
    try {
      const res = await apiGet<ClassOption[]>("/api/classes/");
      return Array.isArray(res) ? res : [];
    } catch {
      return [];
    }
  },
};
