import { apiGet, apiPost } from "@/common/services/api";

export interface AcademicYear {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  is_active?: boolean;
}

export interface CreateAcademicYearPayload {
  name: string;
  start_date: string;
  end_date: string;
  is_active?: boolean;
}

export const academicYearService = {
  getAcademicYears: async (activeOnly = false) => {
    const url = activeOnly
      ? "/api/academics/academic-years?active_only=true"
      : "/api/academics/academic-years";
    const res = await apiGet<{ academic_years: AcademicYear[] }>(url);
    return res.academic_years ?? [];
  },
  createAcademicYear: async (payload: CreateAcademicYearPayload): Promise<AcademicYear> => {
    const res = await apiPost<{ data?: { academic_year?: AcademicYear } }>(
      "/api/academics/academic-years",
      payload
    );
    const ay = (res as any)?.data?.academic_year;
    if (!ay) throw new Error("Failed to create academic year");
    return ay;
  },
};
