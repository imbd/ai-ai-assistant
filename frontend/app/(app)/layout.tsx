import { headers } from 'next/headers';
import { getAppConfig } from '@/lib/utils';
import { GithubLogoIcon } from '@phosphor-icons/react/ssr';

interface AppLayoutProps {
  children: React.ReactNode;
}

export default async function AppLayout({ children }: AppLayoutProps) {
  const hdrs = await headers();
  const { companyName, logo, logoDark } = await getAppConfig(hdrs);

  return (
    <>
      <header className="fixed top-0 left-0 z-50 hidden w-full flex-row justify-between p-6 md:flex">       
        <div className="flex items-center gap-4">          
          <a
            href="https://github.com/imbd/ai-ai-assistant"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="GitHub repository"
            className="opacity-80 transition-opacity hover:opacity-100"
            title="View source on GitHub"
          >
            <GithubLogoIcon size={20} weight="fill" />
          </a>
        </div>
      </header>
      {children}
    </>
  );
}
