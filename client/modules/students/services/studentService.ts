import { apiDelete, apiGet, apiPost, apiPut } from '@/common/services/api';
import { Student, CreateStudentDTO, UpdateStudentDTO, CreateStudentResponse } from '../types';

export const studentService = {
  // Get all students (Admin) or class students (Teacher)
  getStudents: async (params?: {
    class_id?: string;
    class_ids?: string[];
    academic_year_id?: string;
    search?: string;
  }) => {
    let url = '/api/students/';
    if (params) {
      const query = new URLSearchParams();
      if (params.class_ids?.length)
        query.append('class_ids', params.class_ids.join(','));
      else if (params.class_id) query.append('class_id', params.class_id);
      if (params.academic_year_id) query.append('academic_year_id', params.academic_year_id);
      if (params.search) query.append('search', params.search);
      const queryString = query.toString();
      if (queryString) url += `?${queryString}`;
    }
    return await apiGet<Student[]>(url);
  },

  // Get single student
  getStudent: async (id: string) => {
    return await apiGet<Student>(`/api/students/${id}`);
  },

  // Get current user's student profile
  getMyProfile: async () => {
    return await apiGet<Student>('/api/students/me');
  },

  // Create student (may return credentials if email provided)
  createStudent: async (data: CreateStudentDTO) => {
    return await apiPost<CreateStudentResponse>('/api/students', data);
  },

  // Update student
  updateStudent: async (id: string, data: UpdateStudentDTO) => {
    return await apiPut<Student>(`/api/students/${id}`, data);
  },

  // Delete student
  deleteStudent: async (id: string) => {
    return await apiDelete<Student>(`/api/students/${id}`);
  },
};
