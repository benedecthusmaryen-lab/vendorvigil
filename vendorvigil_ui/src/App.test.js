import { render, screen } from '@testing-library/react';
import App from './App';

test('renders VendorVigil header', () => {
  render(<App />);
  const header = screen.getByText(/VendorVigil/i);
  expect(header).toBeInTheDocument();
});

test('renders risk triage subtitle', () => {
  render(<App />);
  const subtitle = screen.getByText(/Risk Triage/i);
  expect(subtitle).toBeInTheDocument();
});
