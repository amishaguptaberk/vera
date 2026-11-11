import { redirect } from 'next/navigation';

// The Cases queue is the landing route.
export default function Home() {
  redirect('/cases');
}
