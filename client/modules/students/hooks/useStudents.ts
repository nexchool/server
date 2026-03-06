import { useState, useCallback } from 'react';
import { studentService } from '../services/studentService';
import { Student, CreateStudentDTO, UpdateStudentDTO, CreateStudentResponse } from '../types';

export const useStudents = () => {
  const [students, setStudents] = useState<Student[]>([]);
  const [currentStudent, setCurrentStudent] = useState<Student | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStudents = useCallback(async (params?: { class_id?: string; academic_year_id?: string; search?: string }) => {
    setLoading(true);
    setError(null);
    try {
      const data = await studentService.getStudents(params);
      setStudents(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch students');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchStudent = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await studentService.getStudent(id);
      setCurrentStudent(data);
      return data;
    } catch (err: any) {
      setError(err.message || 'Failed to fetch student details');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchMyProfile = useCallback(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await studentService.getMyProfile();
        setCurrentStudent(data);
      } catch (err: any) {
        setError(err.message || 'Failed to fetch profile');
      } finally {
        setLoading(false);
      }
    }, []);

  const createStudent = useCallback(async (data: CreateStudentDTO): Promise<CreateStudentResponse> => {
    setLoading(true);
    setError(null);
    try {
      const response = await studentService.createStudent(data);
      setStudents(prev => [...prev, response.student]);
      return response;
    } catch (err: any) {
      setError(err.message || 'Failed to create student');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const updateStudent = useCallback(async (id: string, data: UpdateStudentDTO): Promise<Student> => {
    setLoading(true);
    setError(null);
    try {
      const updatedStudent = await studentService.updateStudent(id, data);
      // Update in list if present
      setStudents(prev => prev.map(s => s.id === id ? updatedStudent : s));
      // Update current student if it's the one being updated
      if (currentStudent?.id === id) {
        setCurrentStudent(updatedStudent);
      }
      return updatedStudent;
    } catch (err: any) {
      setError(err.message || 'Failed to update student');
      throw err;
    } finally {
      setLoading(false);
    }
  }, [currentStudent]);

  const deleteStudent = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      await studentService.deleteStudent(id);
      setStudents(prev => prev.filter(s => s.id !== id));
    } catch (err: any) {
      setError(err.message || 'Failed to delete student');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    students,
    currentStudent,
    loading,
    error,
    fetchStudents,
    fetchStudent,
    fetchMyProfile,
    createStudent,
    updateStudent,
    deleteStudent,
  };
};
