import React from 'react';
import { FaProjectDiagram } from 'react-icons/fa';

type RootFieldTitleProps = {
  title: string;
};

export const RootFieldTitle = ({ title }: RootFieldTitleProps) => {
  return (
    <div className="flex font-semibold items-center cursor-pointer text-gray-900 w-max whitespace-nowrap hover:text-gray-900">
      <FaProjectDiagram className="w-4 mr-xs h-5 w-5" /> {title}
    </div>
  );
};
