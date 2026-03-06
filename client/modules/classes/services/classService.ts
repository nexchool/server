import { apiDelete, apiGet, apiPost, apiPut } from "@/common/services/api";
import { ClassItem, ClassDetail, CreateClassDTO } from "../types";
import { Student } from "@/modules/students/types";
import { Teacher } from "@/modules/teachers/types";

export const classService = {
  getClasses: async (params?: { academic_year_id?: string }) => {
    let url = "/api/classes/";
    if (params?.academic_year_id) {
      url += `?academic_year_id=${params.academic_year_id}`;
    }
    return await apiGet<ClassItem[]>(url);
  },

  getClassDetail: async (id: string) => {
    return await apiGet<ClassDetail>(`/api/classes/${id}`);
  },

  createClass: async (data: CreateClassDTO) => {
    return await apiPost<ClassItem>("/api/classes/", data);
  },

  updateClass: async (id: string, data: Partial<CreateClassDTO>) => {
    return await apiPut<ClassItem>(`/api/classes/${id}`, data);
  },

  deleteClass: async (id: string) => {
    return await apiDelete<void>(`/api/classes/${id}`);
  },

  // Assignment APIs
  assignStudent: async (classId: string, studentId: string) => {
    return await apiPost<void>(`/api/classes/${classId}/students`, { student_id: studentId });
  },

  removeStudent: async (classId: string, studentId: string) => {
    return await apiDelete<void>(`/api/classes/${classId}/students/${studentId}`);
  },

  assignTeacher: async (classId: string, teacherId: string, subject?: string) => {
    return await apiPost<void>(`/api/classes/${classId}/teachers`, {
      teacher_id: teacherId,
      subject,
    });
  },

  removeTeacher: async (classId: string, teacherId: string) => {
    return await apiDelete<void>(`/api/classes/${classId}/teachers/${teacherId}`);
  },

  getUnassignedStudents: async (classId: string) => {
    return await apiGet<Student[]>(`/api/classes/${classId}/unassigned-students`);
  },

  getUnassignedTeachers: async (classId: string) => {
    return await apiGet<Teacher[]>(`/api/classes/${classId}/unassigned-teachers`);
  },

  /** Teachers who can be selected as class teacher (excludes those already class teacher elsewhere) */
  getAvailableClassTeachers: async () => {
    return await apiGet<Teacher[]>(`/api/classes/meta/available-class-teachers`);
  },
};
