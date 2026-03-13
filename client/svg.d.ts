declare module '*.svg' {
  import React from 'react';
  // eslint-disable-next-line import/no-unresolved -- optional peer, may not be installed
  import { SvgProps } from 'react-native-svg';
  const content: React.FC<SvgProps>;
  export default content;
}

