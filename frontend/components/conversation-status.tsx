import React from 'react';

export type ConversationSectionStatus = 'pending' | 'active' | 'complete';

export interface ConversationSection {
	id: string;
	title: string;
	status: ConversationSectionStatus;
}

interface ConversationStatusProps {
	sections: ConversationSection[];
	className?: string;
}

export function ConversationStatus({ sections, className }: ConversationStatusProps) {
	return (
		<aside className={className} aria-label="Conversation status">
			<h2 className="text-sm font-semibold tracking-wide text-fg1 uppercase">Conversation status</h2>
			<ol className="mt-3 space-y-2">
				{sections.map((section) => {
					const isComplete = section.status === 'complete';
					const isActive = section.status === 'active';
					return (
						<li key={section.id} className="flex items-center gap-3 text-base">
							<span
								className={
									'inline-flex h-5 w-5 items-center justify-center rounded-full border text-[12px] ' +
									(isComplete
										? 'border-green-500 text-white bg-green-500'
										: isActive
										? 'border-blue-500 text-blue-600'
										: 'border-fg2 text-fg2')
								}
								aria-hidden
							>
								{isComplete ? '✓' : ''}
							</span>
							<span className={isActive ? 'text-fg0 font-semibold' : 'text-fg1'}>
								{section.title.replace(/^\d+\.\s*/, '')}
							</span>
						</li>
					);
				})}
			</ol>
		</aside>
	);
} 